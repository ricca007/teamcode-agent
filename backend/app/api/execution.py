"""Framework-neutral execution API and optional FastAPI adapter."""

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
    SessionNotFoundError,
    TaskAlreadyRunningError,
    WorkspaceError,
)


def _http_status(response: dict[str, Any]) -> int:
    if response.get("ok"):
        return 200
    code = response.get("error", {}).get("code")
    return {
        "permission_denied": 403,
        "session_not_found": 404,
        "task_already_running": 409,
        "task_conflict": 409,
        "invalid_state_transition": 409,
        "invalid_request": 400,
        "git_error": 400,
        "adapter_error": 502,
        "execution_error": 500,
    }.get(code, 400)


def _error_response(exc: Role2Error) -> dict[str, Any]:
    if isinstance(exc, PermissionDeniedError):
        code = "permission_denied"
    elif isinstance(exc, InvalidTaskError):
        code = "task_conflict"
    elif isinstance(exc, SessionNotFoundError):
        code = "session_not_found"
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
    execution chain before A introduces FastAPI. ``create_fastapi_router`` can
    wrap this facade once FastAPI is available.
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


def create_fastapi_router(service: ExecutionService):
    """Return a FastAPI router when FastAPI is installed.

    This function is intentionally lazy so role-2 unit tests remain dependency
    free. The router shape follows the paths in ``team_division.md``.
    """

    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("FastAPI and Pydantic are required for create_fastapi_router") from exc

    class RunRequest(BaseModel):
        project_id: str
        actor_id: str
        task: dict[str, Any]
        adapter_name: str | None = None
        prompt: str | None = None
        context: dict[str, Any] | None = None

    api = ExecutionAPI(service)
    router = APIRouter()

    @router.post("/api/tasks/{task_id}/run")
    async def run_task(task_id: str, request: RunRequest):
        payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
        payload["task"]["task_id"] = task_id
        response = await api.run(payload)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.post("/api/tasks/{task_id}/pause")
    async def pause_task(task_id: str, actor_id: str):
        response = await api.pause(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str, actor_id: str):
        response = await api.resume(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.post("/api/tasks/{task_id}/terminate")
    async def terminate_task(task_id: str, actor_id: str):
        response = await api.terminate(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.get("/api/tasks/{task_id}/status")
    async def task_status(task_id: str, actor_id: str):
        response = await api.status(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.get("/api/tasks/{task_id}/logs")
    async def task_logs(task_id: str, actor_id: str):
        response = await api.logs(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.post("/api/tasks/{task_id}/commit")
    async def commit_task(task_id: str, actor_id: str, payload: dict[str, Any]):
        response = await api.commit(task_id, actor_id, str(payload.get("message", "")))
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    @router.get("/api/tasks/{task_id}/changes")
    async def task_changes(task_id: str, actor_id: str):
        response = await api.changes(task_id, actor_id)
        if not response["ok"]:
            raise HTTPException(status_code=_http_status(response), detail=response["error"])
        return response

    return router
