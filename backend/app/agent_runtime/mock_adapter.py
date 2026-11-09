"""Deterministic adapter used for tests, demos and integration work."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from app.schemas.core import AgentLog, AgentStatus, ChangeSet, SessionInfo, TaskSpec

from ..errors import AdapterError, InvalidStateTransitionError, SessionNotFoundError


def _now() -> datetime:
    return datetime.now(UTC)


def _inside(workspace: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(workspace.resolve())
        return True
    except (OSError, ValueError):
        return False


def _safe_output_path(workspace: Path, relative_path: str) -> Path:
    raw = os.fspath(relative_path)
    if not raw or "\x00" in raw:
        raise AdapterError("mock output path is empty or contains NUL")
    windows_style = PureWindowsPath(raw)
    if windows_style.is_absolute() or bool(windows_style.drive) or os.path.isabs(raw):
        raise AdapterError("mock output path must be relative")
    normalized = raw.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        raise AdapterError("mock output path contains parent traversal")
    if any(part in {".git", ".teamcode"} for part in parts):
        raise AdapterError("mock output path is reserved metadata")
    target = workspace.joinpath(*PurePosixPath(normalized).parts)
    if not _inside(workspace, target):
        raise AdapterError(f"mock output escapes workspace: {relative_path}")
    return target


@dataclass
class _MockSession:
    info: SessionInfo
    workspace: Path
    logs: list[AgentLog] = field(default_factory=list)
    changes: ChangeSet = field(default_factory=ChangeSet)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    writes: dict[str, str] = field(default_factory=dict)
    next_sequence: int = 0
    finished: bool = False


class MockAdapter:
    """A fake agent that can optionally write deterministic output files.

    ``context["write_files"]`` accepts a mapping of workspace-relative paths to
    text content. This makes it possible to exercise Git and permission checks
    without invoking a real LLM.
    """

    name = "mock"

    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self._sessions: dict[str, _MockSession] = {}

    def _get(self, session_id: str) -> _MockSession:
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
        if env is not None and not isinstance(env, dict):
            raise AdapterError("env must be a mapping")
        session_id = f"mock-{uuid.uuid4().hex[:12]}"
        info = SessionInfo(
            session_id=session_id,
            task_id=task.task_id,
            adapter=self.name,
            status=AgentStatus.PENDING,
            workspace=str(workspace.resolve()),
        )
        session = _MockSession(info=info, workspace=workspace.resolve())
        session.pause_event.set()
        self._sessions[session_id] = session
        return info

    async def _emit(
        self,
        session: _MockSession,
        level: str,
        message: str,
    ) -> AgentLog:
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
        return log

    async def _finish(self, session: _MockSession, status: AgentStatus) -> None:
        if session.finished:
            return
        session.finished = True
        session.info = session.info.with_status(status, ended_at=_now())
        await session.queue.put(None)

    async def send_task(
        self,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        session = self._get(session_id)
        if session.info.status != AgentStatus.PENDING:
            raise InvalidStateTransitionError(
                f"mock session {session_id} is {session.info.status.value}"
            )
        session.pause_event.set()
        session.info = session.info.with_status(AgentStatus.RUNNING)
        await self._emit(session, "info", "task accepted")
        if self.delay:
            await asyncio.sleep(self.delay)
        await session.pause_event.wait()
        if session.finished:
            return

        if self.fail:
            await self._emit(session, "error", "mock failure requested")
            await self._finish(session, AgentStatus.FAILED)
            return

        if context is not None and not isinstance(context, dict):
            await self._emit(session, "error", "context must be a mapping")
            await self._finish(session, AgentStatus.FAILED)
            return
        write_files = (context or {}).get("write_files", {})
        if not isinstance(write_files, dict):
            await self._emit(session, "error", "context.write_files must be a mapping")
            await self._finish(session, AgentStatus.FAILED)
            return

        try:
            for relative_path, content in write_files.items():
                target = _safe_output_path(session.workspace, str(relative_path))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                session.writes[str(relative_path)] = str(content)
                await self._emit(session, "info", f"wrote {relative_path}")
                await session.pause_event.wait()
                if session.finished:
                    return
        except (OSError, AdapterError) as exc:
            await self._emit(session, "error", str(exc))
            await self._finish(session, AgentStatus.FAILED)
            return

        diff = "".join(
            "diff --git a/{0} b/{0}\n--- /dev/null\n+++ b/{0}\n{1}\n".format(
                path, "".join(f"+{line}\n" for line in content.splitlines())
            )
            for path, content in sorted(session.writes.items())
        )
        session.changes = ChangeSet.from_values(
            files=session.writes.keys(),
            diff=diff,
            commit_hash=None,
        )
        await self._emit(session, "info", "task completed")
        await self._finish(session, AgentStatus.SUCCEEDED)

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
        return self._get(session_id).changes

    async def pause(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status not in {AgentStatus.PENDING, AgentStatus.RUNNING}:
            raise InvalidStateTransitionError(f"cannot pause {session.info.status.value}")
        session.pause_event.clear()
        session.info = session.info.with_status(AgentStatus.PAUSED)

    async def resume(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status != AgentStatus.PAUSED:
            raise InvalidStateTransitionError(f"cannot resume {session.info.status.value}")
        session.pause_event.set()
        session.info = session.info.with_status(AgentStatus.RUNNING)

    async def terminate(self, session_id: str) -> None:
        session = self._get(session_id)
        if session.info.status.terminal:
            raise InvalidStateTransitionError("session already terminal")
        session.pause_event.set()
        await self._emit(session, "warning", "session terminated by operator")
        await self._finish(session, AgentStatus.TERMINATED)
