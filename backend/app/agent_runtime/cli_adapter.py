"""Adapter for non-interactive CLI Coding Agents.

The command is always executed with ``asyncio.create_subprocess_exec``; user
input is never interpolated into a shell command. Prompt delivery supports
three safe modes:

- ``file``: replace ``{prompt_file}`` in the command template, or append the
  generated prompt-file path.
- ``arg``: append the prompt as one argument.
- ``stdin``: write the prompt to the child process standard input.
"""

from __future__ import annotations

import asyncio
import os
import signal
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.schemas.core import AgentLog, AgentStatus, ChangeSet, SessionInfo, TaskSpec

from ..errors import AdapterError, InvalidStateTransitionError, SessionNotFoundError
from ..git_ops.workspace import collect_changes


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CLIAdapterConfig:
    command: tuple[str, ...]
    prompt_mode: str = "file"
    timeout: float | None = None
    prompt_placeholder: str = "{prompt_file}"
    prompt_filename: str = "prompt.txt"

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(part, str) for part in self.command):
            raise ValueError("command must be a non-empty sequence of strings")
        if not self.prompt_placeholder or not self.prompt_filename:
            raise ValueError("prompt_placeholder and prompt_filename must not be empty")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.prompt_mode not in {"file", "arg", "stdin"}:
            raise ValueError("prompt_mode must be file, arg, or stdin")
        if self.prompt_mode != "file" and any(
            self.prompt_placeholder in part for part in self.command
        ):
            raise ValueError("prompt placeholder is only valid in file mode")
        if (
            Path(self.prompt_filename).name != self.prompt_filename
            or "/" in self.prompt_filename
            or "\\" in self.prompt_filename
            or self.prompt_filename in {".", ".."}
        ):
            raise ValueError("prompt_filename must be a plain file name")


@dataclass
class _CLISession:
    info: SessionInfo
    workspace: Path
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    logs: list[AgentLog] = field(default_factory=list)
    process: asyncio.subprocess.Process | None = None
    next_sequence: int = 0
    changes: ChangeSet | None = None
    base_env: dict[str, str] = field(default_factory=dict)
    reader_tasks: list[asyncio.Task] = field(default_factory=list)
    finished: bool = False


class CLIAdapter:
    name = "cli"

    def __init__(self, config: CLIAdapterConfig) -> None:
        self.config = config
        self._sessions: dict[str, _CLISession] = {}

    def _get(self, session_id: str) -> _CLISession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(session_id) from exc

    async def start_session(
        self,
        task: TaskSpec,
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SessionInfo:
        if not workspace.exists() or not workspace.is_dir():
            raise AdapterError(f"workspace directory does not exist: {workspace}")
        session_id = f"cli-{uuid.uuid4().hex[:12]}"
        info = SessionInfo(
            session_id=session_id,
            task_id=task.task_id,
            adapter=self.name,
            status=AgentStatus.PENDING,
            workspace=str(workspace.resolve()),
        )
        if env is not None and not isinstance(env, dict):
            raise AdapterError("env must be a mapping")
        self._sessions[session_id] = _CLISession(
            info=info,
            workspace=workspace.resolve(),
            base_env={str(key): str(value) for key, value in (env or {}).items()},
        )
        return info

    async def _finish(self, session: _CLISession, status: AgentStatus) -> None:
        if session.finished:
            return
        session.finished = True
        session.info = session.info.with_status(status, ended_at=_now())
        await session.queue.put(None)

    async def _emit(self, session: _CLISession, level: str, message: str) -> None:
        log = AgentLog(
            session_id=session.info.session_id,
            task_id=session.info.task_id,
            ts=_now(),
            level=level,
            message=message,
            sequence=session.next_sequence,
        )
        session.next_sequence += 1
        session.logs.append(log)
        await session.queue.put(log)

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        session: _CLISession,
        level: str,
    ) -> None:
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            await self._emit(session, level, raw.decode("utf-8", errors="replace").rstrip())

    def _build_command(self, prompt_path: Path | None) -> list[str]:
        command: list[str] = []
        replaced = False
        for part in self.config.command:
            if self.config.prompt_placeholder in part:
                if prompt_path is None:
                    raise AdapterError("prompt file mode requires a prompt file")
                command.append(part.replace(self.config.prompt_placeholder, str(prompt_path)))
                replaced = True
            else:
                command.append(part)
        if self.config.prompt_mode == "file" and not replaced:
            if prompt_path is None:
                raise AdapterError("prompt file mode requires a prompt file")
            command.append(str(prompt_path))
        return command

    async def send_task(
        self,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        session = self._get(session_id)
        if session.info.status != AgentStatus.PENDING:
            raise InvalidStateTransitionError(
                f"CLI session {session_id} is {session.info.status.value}"
            )
        if context is not None and not isinstance(context, dict):
            raise AdapterError("context must be a mapping")
        extra_env = (context or {}).get("env", {})
        if not isinstance(extra_env, dict):
            raise AdapterError("context.env must be a mapping")
        session.info = session.info.with_status(AgentStatus.RUNNING)

        prompt_path: Path | None = None
        try:
            if self.config.prompt_mode == "file":
                prompt_dir = session.workspace / ".teamcode" / "prompts"
                prompt_dir.mkdir(parents=True, exist_ok=True)
                prompt_path = prompt_dir / f"{session_id}-{self.config.prompt_filename}"
                prompt_path.write_text(prompt, encoding="utf-8")
            command = self._build_command(prompt_path)
        except (OSError, AdapterError, ValueError) as exc:
            await self._emit(session, "error", f"failed to prepare CLI task: {exc}")
            await self._finish(session, AgentStatus.FAILED)
            raise AdapterError(str(exc)) from exc

        env = {
            **os.environ,
            **session.base_env,
            **{str(key): str(value) for key, value in extra_env.items()},
        }
        stdin = (
            asyncio.subprocess.PIPE
            if self.config.prompt_mode == "stdin"
            else asyncio.subprocess.DEVNULL
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(session.workspace),
                env=env,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            await self._emit(session, "error", f"failed to start CLI: {exc}")
            await self._finish(session, AgentStatus.FAILED)
            raise AdapterError(str(exc)) from exc

        session.process = process
        if self.config.prompt_mode == "stdin":
            if process.stdin is None:
                await self._emit(session, "error", "CLI stdin is unavailable")
                process.kill()
                await process.wait()
                await self._finish(session, AgentStatus.FAILED)
                raise AdapterError("CLI stdin is unavailable")
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError) as exc:
                await self._emit(session, "warning", f"CLI closed stdin early: {exc}")

        readers = [
            asyncio.create_task(self._read_stream(process.stdout, session, "stdout")),
            asyncio.create_task(self._read_stream(process.stderr, session, "stderr")),
        ]
        session.reader_tasks = readers

        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=self.config.timeout,
            )
            await asyncio.gather(*readers)
            exit_code = process.returncode
            if exit_code == 0:
                await self._emit(session, "info", "CLI exited with code 0")
                status = AgentStatus.SUCCEEDED
            else:
                await self._emit(session, "error", f"CLI exited with code {exit_code}")
                status = AgentStatus.FAILED
        except TimeoutError as exc:
            process.kill()
            await asyncio.gather(*readers, return_exceptions=True)
            await self._emit(session, "error", "CLI timed out")
            await self._finish(session, AgentStatus.FAILED)
            raise AdapterError("CLI timed out") from exc
        except asyncio.CancelledError:
            process.kill()
            await asyncio.gather(*readers, return_exceptions=True)
            await self._emit(session, "warning", "CLI task cancelled")
            await self._finish(session, AgentStatus.TERMINATED)
            raise
        except Exception as exc:
            process.kill()
            await asyncio.gather(*readers, return_exceptions=True)
            await self._emit(session, "error", f"CLI task failed: {exc}")
            await self._finish(session, AgentStatus.FAILED)
            raise AdapterError(str(exc)) from exc
        finally:
            session.process = None
            session.reader_tasks = []

        await self._finish(session, status)

    async def get_status(self, session_id: str) -> AgentStatus:
        return self._get(session_id).info.status

    async def stream_logs(self, session_id: str) -> AsyncIterator[AgentLog]:
        session = self._get(session_id)
        while True:
            item = await session.queue.get()
            if item is None:
                break
            yield item

    async def get_changes(self, session_id: str) -> ChangeSet:
        session = self._get(session_id)
        if session.changes is None:
            session.changes = await asyncio.to_thread(collect_changes, session.workspace)
        return session.changes

    @staticmethod
    def _signal_process(session: _CLISession, sig: int) -> bool:
        if session.process is None or session.process.returncode is not None:
            return False
        try:
            session.process.send_signal(sig)
        except ProcessLookupError:
            return False
        return True

    async def pause(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status not in {AgentStatus.PENDING, AgentStatus.RUNNING}:
            raise InvalidStateTransitionError(f"cannot pause {session.info.status.value}")
        if session.process is None:
            session.info = session.info.with_status(AgentStatus.PAUSED)
            return
        if os.name != "posix":
            raise AdapterError("pause is only supported on POSIX")
        if not self._signal_process(session, signal.SIGSTOP):
            raise InvalidStateTransitionError("CLI process is no longer running")
        session.info = session.info.with_status(AgentStatus.PAUSED)

    async def resume(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status != AgentStatus.PAUSED:
            raise InvalidStateTransitionError(f"cannot resume {session.info.status.value}")
        if session.process is None:
            session.info = session.info.with_status(AgentStatus.RUNNING)
            return
        if os.name != "posix":
            raise AdapterError("resume is only supported on POSIX")
        if not self._signal_process(session, signal.SIGCONT):
            raise InvalidStateTransitionError("CLI process is no longer running")
        session.info = session.info.with_status(AgentStatus.RUNNING)

    async def terminate(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status.terminal:
            raise InvalidStateTransitionError("session already terminal")
        if session.process is not None and session.process.returncode is None:
            if os.name == "posix":
                # A stopped process will not process SIGTERM until resumed.
                self._signal_process(session, signal.SIGCONT)
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=2)
            except TimeoutError:
                session.process.kill()
                await session.process.wait()
            if session.reader_tasks:
                await asyncio.gather(*session.reader_tasks, return_exceptions=True)
                session.reader_tasks = []
        await self._emit(session, "warning", "session terminated by operator")
        await self._finish(session, AgentStatus.TERMINATED)
