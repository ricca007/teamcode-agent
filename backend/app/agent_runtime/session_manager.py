"""Session state machine, in-memory persistence port and log broadcasting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.core import AgentLog, AgentStatus, ChangeSet, SessionInfo, TaskSpec, utc_now

from ..errors import InvalidStateTransitionError, SessionNotFoundError
from ..log_stream import LogBroker
from .base import CodingAgentAdapter


class SessionStore(Protocol):
    def save_session(self, info: SessionInfo) -> None:
        ...

    def append_log(self, log: AgentLog) -> None:
        ...

    def list_logs(self, session_id: str) -> list[AgentLog]:
        ...

    def save_changes(self, session_id: str, changes: ChangeSet) -> None:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionInfo] = {}
        self.logs: dict[str, list[AgentLog]] = {}
        self.changes: dict[str, ChangeSet] = {}

    def save_session(self, info: SessionInfo) -> None:
        self.sessions[info.session_id] = info

    def append_log(self, log: AgentLog) -> None:
        self.logs.setdefault(log.session_id, []).append(log)

    def list_logs(self, session_id: str) -> list[AgentLog]:
        return list(self.logs.get(session_id, ()))

    def save_changes(self, session_id: str, changes: ChangeSet) -> None:
        self.changes[session_id] = changes


@dataclass
class _ManagedSession:
    project_id: str
    task_id: str
    adapter: CodingAgentAdapter
    info: SessionInfo
    log_task: asyncio.Task | None = None
    changes: ChangeSet | None = None
    log_sequence: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionManager:
    """Coordinates one adapter session and emits ``agent.log`` events."""

    def __init__(
        self,
        store: SessionStore | None = None,
        broker: LogBroker | None = None,
    ) -> None:
        self.store = store or InMemorySessionStore()
        self.broker = broker or LogBroker()
        self._sessions: dict[str, _ManagedSession] = {}

    def _get(self, session_id: str) -> _ManagedSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(session_id) from exc

    async def start_session(
        self,
        project_id: str,
        task: TaskSpec,
        workspace: Any,
        adapter: CodingAgentAdapter,
        env: dict[str, str] | None = None,
    ) -> SessionInfo:
        info = await adapter.start_session(task, workspace, env)
        managed = _ManagedSession(
            project_id=project_id,
            task_id=task.task_id,
            adapter=adapter,
            info=info,
        )
        self._sessions[info.session_id] = managed
        self.store.save_session(info)
        return info

    async def _pump_logs(self, managed: _ManagedSession) -> None:
        try:
            async for log in managed.adapter.stream_logs(managed.info.session_id):
                sequence = managed.log_sequence
                managed.log_sequence += 1
                normalized = AgentLog(
                    session_id=log.session_id,
                    task_id=log.task_id,
                    ts=log.ts,
                    level=log.level,
                    message=log.message,
                    sequence=sequence,
                )
                self.store.append_log(normalized)
                await self._publish(managed, normalized)
        except Exception as exc:
            normalized = AgentLog(
                session_id=managed.info.session_id,
                task_id=managed.task_id,
                ts=utc_now(),
                level="error",
                message=f"log stream failed: {exc}",
                sequence=managed.log_sequence,
            )
            managed.log_sequence += 1
            self.store.append_log(normalized)
            await self._publish(managed, normalized)

    async def _publish(self, managed: _ManagedSession, log: AgentLog) -> None:
        try:
            await self.broker.publish(managed.project_id, log.as_event(managed.project_id))
        except Exception:
            # Persistence already succeeded; a broken WebSocket subscriber must
            # not crash the Agent Runtime log pump.
            return

    async def send_task(
        self,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentStatus:
        managed = self._get(session_id)
        async with managed.lock:
            managed.log_task = asyncio.create_task(self._pump_logs(managed))
            try:
                await managed.adapter.send_task(session_id, prompt, context)
            except Exception:
                if not managed.info.status.terminal:
                    managed.info = managed.info.with_status(AgentStatus.FAILED)
                    self.store.save_session(managed.info)
                if managed.log_task is not None:
                    managed.log_task.cancel()
                raise
            finally:
                if managed.log_task is not None:
                    await asyncio.gather(managed.log_task, return_exceptions=True)

        status = await managed.adapter.get_status(session_id)
        managed.info = managed.info.with_status(status)
        self.store.save_session(managed.info)
        return status

    async def pause(self, session_id: str) -> AgentStatus:
        managed = self._get(session_id)
        async with managed.lock:
            if managed.info.status not in {AgentStatus.PENDING, AgentStatus.RUNNING}:
                raise InvalidStateTransitionError(f"cannot pause {managed.info.status.value}")
            await managed.adapter.pause(session_id)
            managed.info = managed.info.with_status(AgentStatus.PAUSED)
            self.store.save_session(managed.info)
            return managed.info.status

    async def resume(self, session_id: str) -> AgentStatus:
        managed = self._get(session_id)
        async with managed.lock:
            if managed.info.status != AgentStatus.PAUSED:
                raise InvalidStateTransitionError(f"cannot resume {managed.info.status.value}")
            await managed.adapter.resume(session_id)
            managed.info = managed.info.with_status(AgentStatus.RUNNING)
            self.store.save_session(managed.info)
            return managed.info.status

    async def terminate(self, session_id: str) -> AgentStatus:
        managed = self._get(session_id)
        async with managed.lock:
            if managed.info.status.terminal:
                raise InvalidStateTransitionError("session already terminal")
            await managed.adapter.terminate(session_id)
            managed.info = managed.info.with_status(AgentStatus.TERMINATED)
            self.store.save_session(managed.info)
            return managed.info.status

    async def get_status(self, session_id: str) -> AgentStatus:
        managed = self._get(session_id)
        status = await managed.adapter.get_status(session_id)
        if status != managed.info.status:
            managed.info = managed.info.with_status(status)
            self.store.save_session(managed.info)
        return status

    async def wait_for_terminal(
        self,
        session_id: str,
        timeout: float | None = None,
        poll_interval: float = 0.05,
    ) -> SessionInfo:
        """Wait until an external adapter reaches a terminal state."""

        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        self._get(session_id)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            status = await self.get_status(session_id)
            if status.terminal:
                return self.get_session(session_id)
            if deadline is not None and loop.time() >= deadline:
                raise TimeoutError(f"session {session_id} did not finish in time")
            await asyncio.sleep(poll_interval)

    def list_sessions(self, project_id: str | None = None) -> list[SessionInfo]:
        sessions = [
            managed.info
            for managed in self._sessions.values()
            if project_id is None or managed.project_id == project_id
        ]
        return sorted(sessions, key=lambda info: info.started_at)

    async def get_changes(self, session_id: str) -> ChangeSet:
        managed = self._get(session_id)
        changes = await managed.adapter.get_changes(session_id)
        managed.changes = changes
        self.store.save_changes(session_id, changes)
        return changes

    async def mark_failed(self, session_id: str, message: str) -> AgentStatus:
        managed = self._get(session_id)
        managed.info = managed.info.with_status(AgentStatus.FAILED)
        self.store.save_session(managed.info)
        log = AgentLog(
            session_id=session_id,
            task_id=managed.task_id,
            ts=utc_now(),
            level="error",
            message=message,
            sequence=managed.log_sequence,
        )
        managed.log_sequence += 1
        self.store.append_log(log)
        await self._publish(managed, log)
        return managed.info.status

    def list_logs(self, session_id: str) -> list[AgentLog]:
        return self.store.list_logs(session_id)

    def get_session(self, session_id: str) -> SessionInfo:
        return self._get(session_id).info

    async def shutdown(self) -> None:
        """Terminate active sessions and stop log pumps during service shutdown."""

        for managed in list(self._sessions.values()):
            try:
                if not managed.info.status.terminal:
                    await self.terminate(managed.info.session_id)
            except Exception:
                if not managed.info.status.terminal:
                    managed.info = managed.info.with_status(AgentStatus.TERMINATED)
                    self.store.save_session(managed.info)
            if managed.log_task is not None and not managed.log_task.done():
                managed.log_task.cancel()
                await asyncio.gather(managed.log_task, return_exceptions=True)
