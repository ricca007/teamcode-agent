"""Role-2 execution service: TaskSpec -> Worktree -> Adapter -> change check."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.core import AgentStatus, ChangeSet, ExecutionResult, TaskSpec, task_prompt, utc_now

from ..errors import (
    InvalidTaskError,
    PermissionDeniedError,
    SessionNotFoundError,
    TaskAlreadyRunningError,
)
from ..git_ops.workspace import GitWorkspace, commit_changes, create_workspace
from ..log_stream import LogBroker
from ..security.path_policy import validate_allowed_paths, validate_paths
from .base import CodingAgentAdapter
from .session_manager import SessionManager


@dataclass
class ExecutionService:
    repo_root: Path
    sessions: SessionManager
    leader_id: str | None = None
    broker: LogBroker | None = None
    adapter_factory: Callable[[], CodingAgentAdapter] | None = None
    adapter_registry: dict[str, Callable[[], CodingAgentAdapter]] | None = None
    max_concurrent_sessions: int | None = None
    _task_locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False)
    _active_tasks: set = field(default_factory=set, init=False)
    _task_workspaces: dict[str, GitWorkspace] = field(default_factory=dict, init=False)
    _task_specs: dict[str, TaskSpec] = field(default_factory=dict, init=False)
    _task_projects: dict[str, str] = field(default_factory=dict, init=False)
    _run_slots: asyncio.Semaphore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.repo_root = Path(self.repo_root).resolve()
        self.broker = self.broker or self.sessions.broker
        if self.leader_id is not None:
            self.leader_id = str(self.leader_id)
            if not self.leader_id.strip():
                raise ValueError("leader_id must not be empty")
        self._task_sessions: dict[str, str] = {}
        self._task_workspaces = {}
        self._task_specs = {}
        self._task_projects = {}
        self.adapter_registry = dict(self.adapter_registry or {})
        if self.max_concurrent_sessions is not None:
            if self.max_concurrent_sessions <= 0:
                raise ValueError("max_concurrent_sessions must be positive")
            self._run_slots = asyncio.Semaphore(self.max_concurrent_sessions)

    def _task_id(self, task_or_session_id: str) -> str:
        if task_or_session_id in self._task_specs:
            return task_or_session_id
        for task_id, session_id in self._task_sessions.items():
            if session_id == task_or_session_id:
                return task_id
        raise SessionNotFoundError(task_or_session_id)

    def _session_id(self, task_or_session_id: str) -> str:
        return self._task_sessions.get(self._task_id(task_or_session_id), task_or_session_id)

    def authorize(self, actor_id: str, task: TaskSpec) -> None:
        if actor_id != task.owner_id and actor_id != self.leader_id:
            raise PermissionDeniedError(
                f"actor {actor_id} cannot execute task {task.task_id}"
            )

    def authorize_operation(self, actor_id: str, task_or_session_id: str) -> TaskSpec:
        task_id = self._task_id(task_or_session_id)
        task = self._task_specs[task_id]
        self.authorize(actor_id, task)
        return task

    async def run(
        self,
        project_id: str,
        task: TaskSpec,
        actor_id: str,
        adapter: CodingAgentAdapter | None = None,
        adapter_name: str | None = None,
        prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        started_at = utc_now()
        self.authorize(actor_id, task)
        if adapter is None:
            if adapter_name is not None:
                try:
                    adapter = self.adapter_registry[adapter_name]()
                except KeyError as exc:
                    raise ValueError(f"unknown adapter: {adapter_name}") from exc
            elif self.adapter_factory is not None:
                adapter = self.adapter_factory()
            else:
                raise ValueError("adapter, adapter_name, or adapter_factory is required")
        # Validate configured patterns before an agent starts. Changed files are
        # checked again after execution because the agent can create arbitrary
        # files that are not known in advance.
        validate_allowed_paths(self.repo_root, task.allowed_paths)
        if task.task_id in self._active_tasks:
            raise TaskAlreadyRunningError(
                f"task {task.task_id} is already running"
            )
        self._active_tasks.add(task.task_id)
        task_lock = self._task_locks.setdefault(task.task_id, asyncio.Lock())
        try:
            async with task_lock:
                if self._run_slots is not None:
                    async with self._run_slots:
                        return await self._run_locked(
                            project_id, task, adapter, prompt, context, started_at
                        )
                return await self._run_locked(
                    project_id, task, adapter, prompt, context, started_at
                )
        finally:
            self._active_tasks.discard(task.task_id)

    async def _run_locked(
        self,
        project_id: str,
        task: TaskSpec,
        adapter: CodingAgentAdapter,
        prompt: str | None,
        context: dict[str, Any] | None,
        started_at,
    ) -> ExecutionResult:
        previous_project = self._task_projects.get(task.task_id)
        if previous_project is not None and previous_project != project_id:
            raise InvalidTaskError(
                f"task_id {task.task_id} is already registered for project {previous_project}"
            )
        workspace = await asyncio.to_thread(
            create_workspace,
            project_id,
            task.task_id,
            self.repo_root,
            task.base_branch,
        )
        info = await self.sessions.start_session(
            project_id=project_id,
            task=task,
            workspace=workspace.worktree_path,
            adapter=adapter,
        )
        self._task_projects[task.task_id] = project_id
        self._task_sessions[task.task_id] = info.session_id
        self._task_workspaces[task.task_id] = workspace
        self._task_specs[task.task_id] = task
        await self.sessions.send_task(
            info.session_id,
            prompt or task_prompt(task),
            context=context,
        )
        changes = await self.sessions.get_changes(info.session_id)
        validation = validate_paths(
            workspace.worktree_path,
            changes.files,
            task.allowed_paths,
        )
        status = await self.sessions.get_status(info.session_id)
        if validation.rejected:
            status = await self.sessions.mark_failed(
                info.session_id,
                "rejected changed paths: {}".format(
                    ", ".join(path for path, _ in validation.rejected)
                ),
            )
        finished_at = utc_now()
        return ExecutionResult(
            session_id=info.session_id,
            task_id=task.task_id,
            project_id=project_id,
            status=status,
            workspace=str(workspace.worktree_path),
            changes=changes,
            rejected_paths=tuple(path for path, _ in validation.rejected),
            rejection_reasons=tuple(reason for _, reason in validation.rejected),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            log_count=len(self.sessions.list_logs(info.session_id)),
        )

    async def pause(self, task_or_session_id: str, actor_id: str) -> AgentStatus:
        self.authorize_operation(actor_id, task_or_session_id)
        return await self.sessions.pause(self._session_id(task_or_session_id))

    async def resume(self, task_or_session_id: str, actor_id: str) -> AgentStatus:
        self.authorize_operation(actor_id, task_or_session_id)
        return await self.sessions.resume(self._session_id(task_or_session_id))

    async def terminate(self, task_or_session_id: str, actor_id: str) -> AgentStatus:
        self.authorize_operation(actor_id, task_or_session_id)
        return await self.sessions.terminate(self._session_id(task_or_session_id))

    async def status(self, task_or_session_id: str, actor_id: str) -> AgentStatus:
        self.authorize_operation(actor_id, task_or_session_id)
        return await self.sessions.get_status(self._session_id(task_or_session_id))

    def logs(self, task_or_session_id: str, actor_id: str):
        self.authorize_operation(actor_id, task_or_session_id)
        return self.sessions.list_logs(self._session_id(task_or_session_id))

    async def changes(self, task_or_session_id: str, actor_id: str) -> ChangeSet:
        self.authorize_operation(actor_id, task_or_session_id)
        return await self.sessions.get_changes(self._session_id(task_or_session_id))

    async def shutdown(self) -> None:
        await self.sessions.shutdown()
        if self.broker is not None:
            self.broker.close()

    def commit(
        self,
        workspace: GitWorkspace,
        task: TaskSpec,
        actor_id: str,
        message: str,
    ) -> str:
        self.authorize(actor_id, task)
        return commit_changes(workspace, task.allowed_paths, message)

    def commit_task(self, task_or_session_id: str, actor_id: str, message: str) -> str:
        task = self.authorize_operation(actor_id, task_or_session_id)
        task_id = task.task_id
        if task_id not in self._task_workspaces:
            raise SessionNotFoundError(task_or_session_id)
        return commit_changes(
            self._task_workspaces[task_id],
            task.allowed_paths,
            message,
        )
