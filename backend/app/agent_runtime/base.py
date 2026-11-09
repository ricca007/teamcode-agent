"""Adapter protocol for pluggable CLI Coding Agents."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.schemas.core import AgentLog, AgentStatus, ChangeSet, SessionInfo, TaskSpec


@runtime_checkable
class CodingAgentAdapter(Protocol):
    name: str

    async def start_session(
        self,
        task: TaskSpec,
        workspace: Path,
        env: dict[str, str] | None = None,
    ) -> SessionInfo:
        ...

    async def send_task(
        self,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def get_status(self, session_id: str) -> AgentStatus:
        ...

    def stream_logs(self, session_id: str) -> AsyncIterator[AgentLog]:
        ...

    async def get_changes(self, session_id: str) -> ChangeSet:
        ...

    async def pause(self, session_id: str) -> None:
        ...

    async def resume(self, session_id: str) -> None:
        ...

    async def terminate(self, session_id: str) -> None:
        ...
