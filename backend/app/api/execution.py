"""Framework-neutral execution API facade for the agent runtime."""

from __future__ import annotations

from typing import Any

from app.schemas.core import TaskSpec

from ..agent_runtime.execution import ExecutionService
from ..errors import (
    AdapterError,
    InvalidStateTransitionError,
    InvalidTaskError,
    PermissionDeniedError,
    Role2Error,
    SessionAlreadyExistsError,
    SessionNotFoundError,
    TaskAlreadyRunningError,
    WorkspaceError,
)


def _error_response(exc: Role2Error) -> dict[str, Any]:
    if isinstance(exc, PermissionDeniedError):
        code = "permission_denied"
    elif isinstance(exc, InvalidTaskError):
        code = "task_conflict"
    elif isinstance(exc, SessionNotFoundError):
        code = "session_not_found"
    elif isinstance(exc, SessionAlreadyExistsError):
        code = "session_already_exists"
    elif isinstance(exc, InvalidStateTransitionError):
        code = "invalid_state_transition"
    elif isinstance(exc, WorkspaceError):
        code = "git_error"
    elif isinstance(exc, AdapterError):
        code = "adapter_error"
    else:
        code = "execution_error"
    return {"ok": False, "error": {"code": code, "message": str(exc)}}


class ExecutionAPI:
    """Synchronous request facade for B-4.

    Keeping the request handler framework-neutral lets the group test the task
    execution chain independently of FastAPI. The production HTTP surface is
    served by ``app.integration.api``; this module is retained for
    framework-neutral testing and as a reference contract.
    """

    def __init__(self, service: ExecutionService) -> None:
        self.service = service

    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            task = TaskSpec.from_mapping(request["task"])
            result = await self.service.run(
                project_id=str(request["project_id"]),
                task=task,
                actor_id=str(request["actor_id"]),
                adapter=request.get("adapter"),
                adapter_name=request.get("adapter_name"),
                prompt=request.get("prompt"),
                context=request.get("context"),
            )
            return {"ok": True, "result": result.as_dict()}
        except PermissionDeniedError as exc:
            return {"ok": False, "error": {"code": "permission_denied", "message": str(exc)}}
        except TaskAlreadyRunningError as exc:
            return {"ok": False, "error": {"code": "task_already_running", "message": str(exc)}}
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
        except Role2Error as exc:
            return _error_response(exc)

    async def pause(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        return await self._status_action("pause", task_or_session_id, actor_id)

    async def resume(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        return await self._status_action("resume", task_or_session_id, actor_id)

    async def terminate(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        return await self._status_action("terminate", task_or_session_id, actor_id)

    async def status(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        return await self._status_action("status", task_or_session_id, actor_id)

    async def _status_action(
        self,
        action: str,
        task_or_session_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        try:
            method = getattr(self.service, action)
            status = await method(task_or_session_id, actor_id)
            return {"ok": True, "task_or_session_id": task_or_session_id, "status": status.value}
        except Role2Error as exc:
            return _error_response(exc)

    async def logs(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        try:
            logs = self.service.logs(task_or_session_id, actor_id)
            return {
                "ok": True,
                "logs": [
                    {
                        "session_id": log.session_id,
                        "task_id": log.task_id,
                        "ts": log.ts.isoformat(),
                        "level": log.level,
                        "message": log.message,
                        "sequence": log.sequence,
                    }
                    for log in logs
                ],
            }
        except Role2Error as exc:
            return _error_response(exc)

    async def commit(self, task_or_session_id: str, actor_id: str, message: str) -> dict[str, Any]:
        try:
            commit_hash = self.service.commit_task(task_or_session_id, actor_id, message)
            return {
                "ok": True,
                "task_or_session_id": task_or_session_id,
                "commit_hash": commit_hash,
            }
        except Role2Error as exc:
            return _error_response(exc)

    async def changes(self, task_or_session_id: str, actor_id: str) -> dict[str, Any]:
        try:
            changes = await self.service.changes(task_or_session_id, actor_id)
            return {
                "ok": True,
                "changes": {
                    "files": list(changes.files),
                    "diff": changes.diff,
                    "commit_hash": changes.commit_hash,
                },
            }
        except Role2Error as exc:
            return _error_response(exc)

    async def cleanup(
        self,
        task_or_session_id: str,
        actor_id: str,
        delete_branch: bool = False,
    ) -> dict[str, Any]:
        try:
            await self.service.cleanup(
                task_or_session_id,
                actor_id,
                delete_branch=delete_branch,
            )
            return {"ok": True, "task_or_session_id": task_or_session_id}
        except Role2Error as exc:
            return _error_response(exc)
