"""A/B/C 整合链路测试：规划 → 任务落库 → 执行 → 日志/变更 → 事件。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.realtime.manager import bus

REQUIREMENTS = "在线商城：用户管理、商品管理、订单管理，需要优惠券功能。"


async def _create_project(client, repo: Path) -> str:
    response = await client.post(
        "/api/projects",
        json={
            "name": "集成演示",
            "repo_path": str(repo),
            "owner_id": "u_lead",
            "owner_name": "Leader",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _plan(client, project_id: str, mode: str = "plan") -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": REQUIREMENTS,
            "members": [
                {"member_id": "u_a", "name": "成员 A", "areas": ["user", "product"]},
                {"member_id": "u_b", "name": "成员 B", "areas": ["order", "coupon"]},
            ],
            "max_tasks": 6,
            "mode": mode,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _tasks(client, project_id: str) -> list[dict]:
    response = await client.get(f"/api/projects/{project_id}/tasks")
    assert response.status_code == 200, response.text
    return response.json()["tasks"]


async def _wait_terminal(client, task_id: str, timeout: float = 10.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last: dict | None = None
    while loop.time() < deadline:
        response = await client.get(f"/api/tasks/{task_id}/status")
        if response.status_code == 200:
            last = response.json()
            if last["status"] in {"succeeded", "failed", "terminated"}:
                return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"等待会话结束超时，最后状态: {last}")


async def test_plan_persists_tasks_and_plan(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    result = await _plan(client, project_id)

    assert result["version"] == 1
    assert len(result["plan"]["tasks"]) >= 3

    tasks = await _tasks(client, project_id)
    assert len(tasks) == len(result["plan"]["tasks"])
    assert {task["task_id"] for task in tasks} == {
        task["task_id"] for task in result["plan"]["tasks"]
    }
    assert all(task["owner_id"] in {"u_a", "u_b"} for task in tasks)
    assert any(task["depends_on"] for task in tasks)

    plan_response = await client.get(f"/api/projects/{project_id}/plan")
    assert plan_response.status_code == 200
    assert plan_response.json()["version"] == 1

    members = await client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    assert {item["user_id"] for item in members.json()["members"]} == {
        "u_lead",
        "u_a",
        "u_b",
    }


async def test_run_task_persists_logs_changes_and_events(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    tasks = await _tasks(client, project_id)
    task = tasks[0]

    received: list[dict] = []
    sink = received.append
    bus.add_sink(sink)
    try:
        run = await client.post(
            f"/api/tasks/{task['task_id']}/run",
            json={
                "actor_id": task["owner_id"],
                "adapter_name": "mock",
            },
        )
        assert run.status_code == 200, run.text
        payload = run.json()
        assert payload["session_id"]
        assert payload["status"] in {"pending", "running"}

        status = await _wait_terminal(client, task["task_id"])
        assert status["status"] == "succeeded"

        logs = await client.get(f"/api/tasks/{task['task_id']}/logs")
        assert logs.status_code == 200
        assert logs.json()["logs"]

        changes = await client.get(f"/api/tasks/{task['task_id']}/changes")
        assert changes.status_code == 200
        change_rows = changes.json()["changes"]
        assert change_rows
        assert change_rows[0]["files"]

        updated = {item["task_id"]: item for item in await _tasks(client, project_id)}
        assert updated[task["task_id"]]["status"] == "completed"
        assert updated[task["task_id"]]["workspace_path"]

        commit = await client.post(
            f"/api/tasks/{task['task_id']}/commit",
            json={
                "actor_id": task["owner_id"],
                "message": "mock generated service",
            },
        )
        assert commit.status_code == 200, commit.text
        assert commit.json()["commit_hash"]

        await asyncio.sleep(0.1)
        event_types = {event["type"] for event in received}
        assert {"task.updated", "agent.log", "code.changed"} <= event_types
    finally:
        bus.remove_sink(sink)


async def test_non_owner_cannot_run_task(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = (await _tasks(client, project_id))[0]

    response = await client.post(
        f"/api/tasks/{task['task_id']}/run",
        json={"actor_id": "intruder", "adapter_name": "mock"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_replan_increments_version_and_keeps_tasks(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    before = await _tasks(client, project_id)

    result = await _plan(client, project_id, mode="replan")
    assert result["version"] == 2
    assert result["diff"] is not None

    plan_response = await client.get(f"/api/projects/{project_id}/plan")
    assert plan_response.json()["version"] == 2

    after = await _tasks(client, project_id)
    assert {task["task_id"] for task in after} >= {
        task["task_id"] for task in before
    }


async def test_agents_endpoint_lists_configurable_agents(client):
    response = await client.get("/api/agents")
    assert response.status_code == 200
    agents = response.json()["agents"]
    names = {agent["name"] for agent in agents}
    assert {"claude", "codex", "aider"} <= names
    assert "mock" not in names  # 产品接口不暴露测试用 mock
    assert all("available" in agent for agent in agents)


async def test_unknown_agent_is_rejected(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = (await _tasks(client, project_id))[0]

    response = await client.post(
        f"/api/tasks/{task['task_id']}/run",
        json={"actor_id": task["owner_id"], "agent_name": "nope"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_agent"


async def test_merge_updates_main_repo_and_interfaces(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = (await _tasks(client, project_id))[0]
    allowed = task["allowed_paths"][0].rstrip("/")
    target_path = f"{allowed}/merged_feature.py"
    source = (
        "def merged_feature() -> str:\n"
        '    """Merged feature."""\n'
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

    received: list[dict] = []
    sink = received.append
    bus.add_sink(sink)
    try:
        merged = await client.post(
            f"/api/projects/{project_id}/tasks/{task['task_id']}/merge",
            json={"message": "merge merged_feature"},
        )
    finally:
        bus.remove_sink(sink)

    assert merged.status_code == 200, merged.text
    payload = merged.json()
    assert payload["merge_commit"]
    assert (git_repo / target_path).exists()

    listing = await client.get(
        f"/api/projects/{project_id}/interfaces?format=json"
    )
    assert listing.status_code == 200
    names = {item["name"] for item in listing.json()["interfaces"]}
    assert "merged_feature" in names
    assert any(event["type"] == "interface.updated" for event in received)


async def test_project_requires_git_repository(client, tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    response = await client.post(
        "/api/projects",
        json={"name": "无 Git", "repo_path": str(plain)},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "repository_not_git"
