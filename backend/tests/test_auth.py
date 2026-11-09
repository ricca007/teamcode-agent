"""注册制账号、跨项目角色与任务隔离测试。"""

from __future__ import annotations

from pathlib import Path

PASSWORD = "demo-pass-123"


async def _register(client, name: str, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["token"].startswith("tc_")
    return payload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client, token: str, repo: Path, name: str) -> str:
    response = await client.post(
        "/api/projects",
        json={"name": name, "repo_path": str(repo)},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _join_and_approve(
    client, joiner_token: str, leader_token: str, project_id: str
) -> None:
    join = await client.post(
        f"/api/projects/{project_id}/join-requests",
        json={"areas": []},
        headers=_headers(joiner_token),
    )
    assert join.status_code == 200, join.text
    request_id = join.json()["request_id"]
    approved = await client.post(
        f"/api/projects/{project_id}/join-requests/{request_id}/approve",
        json={"areas": []},
        headers=_headers(leader_token),
    )
    assert approved.status_code == 200, approved.text


async def test_register_login_and_cross_project_roles(
    client, git_repo: Path, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    alice = await _register(client, "Alice", "alice@example.invalid")
    alice_headers = _headers(alice["token"])
    project_a = await _create_project(
        client, alice["token"], git_repo, "项目 A"
    )

    me = await client.get("/api/me", headers=alice_headers)
    assert me.status_code == 200
    assert me.json()["user_id"] == alice["user"]["id"]

    bob = await _register(client, "Bob", "bob@example.invalid")
    await _join_and_approve(
        client, bob["token"], alice["token"], project_a
    )
    bob_projects = await client.get(
        "/api/projects", headers=_headers(bob["token"])
    )
    assert bob_projects.status_code == 200
    assert {item["id"]: item["role"] for item in bob_projects.json()["projects"]}[
        project_a
    ] == "member"

    project_b = await _create_project(
        client, bob["token"], git_repo, "项目 B"
    )
    roles = {
        item["id"]: item["role"]
        for item in (
            await client.get("/api/projects", headers=_headers(bob["token"]))
        ).json()["projects"]
    }
    assert roles[project_a] == "member"
    assert roles[project_b] == "leader"

    # 换设备重新登录：同一个 user，项目和角色自动继承
    login = await client.post(
        "/api/auth/login",
        json={"email": "bob@example.invalid", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    new_token = login.json()["token"]
    assert new_token != bob["token"]
    inherited = {
        item["id"]: item["role"]
        for item in (
            await client.get("/api/projects", headers=_headers(new_token))
        ).json()["projects"]
    }
    assert inherited[project_a] == "member"
    assert inherited[project_b] == "leader"


async def test_members_only_see_and_run_own_tasks(
    client, git_repo: Path, monkeypatch
):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    alice = await _register(client, "Alice", "alice2@example.invalid")
    bob = await _register(client, "Bob", "bob2@example.invalid")
    project_id = await _create_project(
        client, alice["token"], git_repo, "隔离项目"
    )
    await _join_and_approve(client, bob["token"], alice["token"], project_id)

    plan = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": "用户管理、商品管理、订单管理",
            "members": [
                {
                    "member_id": alice["user"]["id"],
                    "name": "Alice",
                    "areas": ["user"],
                },
                {
                    "member_id": bob["user"]["id"],
                    "name": "Bob",
                    "areas": ["product", "order"],
                },
            ],
            "max_tasks": 6,
        },
        headers=_headers(alice["token"]),
    )
    assert plan.status_code == 200, plan.text

    bob_tasks = (
        await client.get(
            f"/api/projects/{project_id}/tasks",
            headers=_headers(bob["token"]),
        )
    ).json()["tasks"]
    assert bob_tasks
    assert all(
        task["owner_id"] == bob["user"]["id"] for task in bob_tasks
    )

    alice_tasks = (
        await client.get(
            f"/api/projects/{project_id}/tasks",
            headers=_headers(alice["token"]),
        )
    ).json()["tasks"]
    other = next(
        task for task in alice_tasks if task["owner_id"] != bob["user"]["id"]
    )
    denied = await client.post(
        f"/api/tasks/{other['task_id']}/run",
        json={},
        headers=_headers(bob["token"]),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    anonymous = await client.get(f"/api/projects/{project_id}/tasks")
    assert anonymous.status_code == 401


async def test_api_key_works_and_can_be_revoked(
    client, git_repo: Path, monkeypatch
):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    alice = await _register(client, "Alice", "alice4@example.invalid")
    headers = _headers(alice["token"])
    project_id = await _create_project(client, alice["token"], git_repo, "Key 项目")

    created = await client.post(
        "/api/auth/api-keys",
        json={"name": "coding-agent"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    raw_key = created.json()["raw_key"]
    assert raw_key.startswith("tcak_")
    key_headers = _headers(raw_key)

    projects = await client.get("/api/projects", headers=key_headers)
    assert projects.status_code == 200
    assert projects.json()["projects"][0]["id"] == project_id

    tasks = await client.get(
        f"/api/projects/{project_id}/tasks", headers=key_headers
    )
    assert tasks.status_code == 200
    interfaces = await client.get(
        f"/api/projects/{project_id}/interfaces", headers=key_headers
    )
    assert interfaces.status_code == 200

    anonymous = await client.get(
        f"/api/projects/{project_id}/interfaces"
    )
    assert anonymous.status_code == 401

    revoked = await client.delete(
        f"/api/auth/api-keys/{created.json()['id']}", headers=headers
    )
    assert revoked.status_code == 200
    after = await client.get(
        f"/api/projects/{project_id}/tasks", headers=key_headers
    )
    assert after.status_code == 401


async def test_leader_assigns_placeholder_task_to_member(
    client, git_repo: Path, monkeypatch
):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    alice = await _register(client, "Alice", "alice3@example.invalid")
    bob = await _register(client, "Bob", "bob3@example.invalid")
    project_id = await _create_project(
        client, alice["token"], git_repo, "分配项目"
    )
    await _join_and_approve(client, bob["token"], alice["token"], project_id)

    plan = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": "用户管理、商品管理、订单管理",
            "roles": ["A", "B", "C"],
            "max_tasks": 6,
        },
        headers=_headers(alice["token"]),
    )
    assert plan.status_code == 200, plan.text
    tasks = (
        await client.get(
            f"/api/projects/{project_id}/tasks",
            headers=_headers(alice["token"]),
        )
    ).json()["tasks"]
    assert tasks[0]["owner_id"].startswith("role_")

    assign = await client.post(
        f"/api/projects/{project_id}/tasks/{tasks[0]['task_id']}/assign",
        json={"user_id": bob["user"]["id"]},
        headers=_headers(alice["token"]),
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["owner_id"] == bob["user"]["id"]

    bob_tasks = (
        await client.get(
            f"/api/projects/{project_id}/tasks",
            headers=_headers(bob["token"]),
        )
    ).json()["tasks"]
    assert any(
        task["task_id"] == tasks[0]["task_id"] for task in bob_tasks
    )
