"""合并后清理 Worktree 的回归测试（P1-1）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.integration.service import _runtimes

REQUIREMENTS = "在线商城：用户管理、商品管理，需要优惠券功能。"


async def _create_project(client, repo: Path) -> str:
    response = await client.post(
        "/api/projects",
        json={
            "name": "清理演示",
            "repo_path": str(repo),
            "owner_id": "u_lead",
            "owner_name": "Leader",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _plan(client, project_id: str) -> None:
    response = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": REQUIREMENTS,
            "members": [
                {"member_id": "u_a", "name": "成员 A", "areas": ["user"]},
                {"member_id": "u_b", "name": "成员 B", "areas": ["coupon"]},
            ],
            "max_tasks": 4,
            "mode": "plan",
        },
    )
    assert response.status_code == 200, response.text


async def _first_task(client, project_id: str) -> dict:
    response = await client.get(f"/api/projects/{project_id}/tasks")
    assert response.status_code == 200, response.text
    return response.json()["tasks"][0]


async def _wait_terminal(client, task_id: str, timeout: float = 10.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        response = await client.get(f"/api/tasks/{task_id}/status")
        if response.status_code == 200:
            payload = response.json()
            if payload["status"] in {"succeeded", "failed", "terminated"}:
                return payload
        await asyncio.sleep(0.05)
    raise AssertionError("task did not finish in time")


async def _run_task(client, task: dict) -> dict:
    allowed = task["allowed_paths"][0].rstrip("/")
    target_path = f"{allowed}/cleanup_feature.py"
    source = (
        "def cleanup_feature() -> str:\n"
        '    """Cleanup feature."""\n'
        '    return "ok"\n'
    )
    run = await client.post(
        f"/api/tasks/{task['task_id']}/run",
        json={
            "actor_id": task["owner_id"],
            "context": {"write_files": {target_path: source}},
        },
    )
    assert run.status_code == 200, run.text
    status = await _wait_terminal(client, task["task_id"])
    assert status["status"] == "succeeded"
    return status


async def _merge(client, project_id: str, task_id: str):
    return await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/merge",
        json={"message": f"merge {task_id}"},
    )


async def test_merge_cleans_up_worktree(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = await _first_task(client, project_id)
    status = await _run_task(client, task)

    workspace = Path(status["workspace"])
    assert workspace.is_dir()
    assert workspace.name == task["task_id"]

    merged = await _merge(client, project_id, task["task_id"])
    assert merged.status_code == 200, merged.text
    payload = merged.json()
    assert payload["workspace_cleaned"] is True
    assert payload["workspace_cleanup_error"] is None
    assert not workspace.exists()

    # 第二次合并：Worktree 已被清理，返回 workspace_missing。
    again = await _merge(client, project_id, task["task_id"])
    assert again.status_code == 409
    assert again.json()["code"] == "workspace_missing"


async def test_merge_rejects_running_task(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = await _first_task(client, project_id)
    await _run_task(client, task)

    runtime = _runtimes[project_id]
    runtime.active_tasks.add(task["task_id"])
    try:
        response = await _merge(client, project_id, task["task_id"])
    finally:
        runtime.active_tasks.discard(task["task_id"])

    assert response.status_code == 409
    assert response.json()["code"] == "task_running"
