"""占位角色（A/B/C）应作为可分配成员保留的回归测试。"""

from __future__ import annotations

from pathlib import Path

REQUIREMENTS = "在线商城：用户管理、商品管理、订单管理，需要优惠券功能。"


async def _create_project(client, repo: Path) -> str:
    response = await client.post(
        "/api/projects",
        json={
            "name": "占位角色演示",
            "repo_path": str(repo),
            "owner_id": "u_lead",
            "owner_name": "Leader",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_placeholder_roles_are_assignable_members(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)

    plan = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": REQUIREMENTS,
            "members": [],
            "roles": ["A", "B", "C"],
            "max_tasks": 4,
            "mode": "plan",
        },
    )
    assert plan.status_code == 200, plan.text

    tasks = (
        await client.get(f"/api/projects/{project_id}/tasks")
    ).json()["tasks"]
    assert tasks
    assert {task["owner_id"] for task in tasks} <= {"role_a", "role_b", "role_c"}

    members = (
        await client.get(f"/api/projects/{project_id}/members")
    ).json()["members"]
    member_ids = {member["user_id"] for member in members}
    # 占位角色必须出现在成员列表里，才能在分配下拉框中重新选回 A/B/C。
    assert {"role_a", "role_b", "role_c"} <= member_ids
