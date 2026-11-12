"""课堂主线：通过真实 A/B 入口、数据库与文件系统验证 C 接线。"""

import asyncio
from pathlib import Path

import pytest

from app.integration.api import bootstrap
from app.integration.service import git


def headers(member):
    return {"Authorization": "Bearer " + member["token"]}


@pytest.fixture
async def classroom(client, session_factory, git_repo: Path, monkeypatch):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TEAMCODE_MOCK_DELAY", "0.03")
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_project.py").write_text(
        "def test_project():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )
    git(git_repo, "add", ".")
    git(git_repo, "commit", "-m", "add project test")
    data = await bootstrap(session_factory, git_repo)
    return data["members"]


async def terminal(client, task_id, actor):
    for _ in range(150):
        response = await client.get(f"/api/tasks/{task_id}/status", headers=headers(actor))
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in {"succeeded", "failed", "terminated"}:
            return result
        await asyncio.sleep(0.03)
    pytest.fail("任务未在限定时间结束")


async def test_full_classroom_workflow(client, classroom, git_repo):
    leader, _, member_c = classroom
    rows = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()["tasks"]
    task = next(t for t in rows if t["owner_id"] != member_c["user_id"])
    task_id = task["task_id"]
    denied = await client.post(f"/api/tasks/{task_id}/run", json={}, headers=headers(member_c))
    assert denied.status_code == 403
    started = await client.post(
        f"/api/tasks/{task_id}/run", json={"agent_name": "mock"}, headers=headers(leader)
    )
    assert started.status_code == 200, started.text
    result = await terminal(client, task_id, leader)
    assert result["status"] == "succeeded", result
    assert Path(result["workspace"]) != git_repo
    logs = (await client.get(f"/api/tasks/{task_id}/logs", headers=headers(leader))).json()["logs"]
    changes = (await client.get(f"/api/tasks/{task_id}/changes", headers=headers(leader))).json()[
        "changes"
    ]
    assert logs and changes[0]["files"]
    test_result = await client.post(f"/api/tasks/{task_id}/tests", json={}, headers=headers(leader))
    assert test_result.status_code == 200, test_result.text
    assert test_result.json()["status"] == "passed"
    assert "1 passed" in test_result.json()["output"]
    committed = await client.post(f"/api/tasks/{task_id}/commit", json={}, headers=headers(leader))
    assert committed.status_code == 200, committed.text
    merged = await client.post(
        f"/api/projects/p_demo/tasks/{task_id}/merge",
        json={"message": "review demo"},
        headers=headers(leader),
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["merged"]
    assert (git_repo / changes[0]["files"][0]).is_file()
    listing = (await client.get("/api/projects/p_demo/interfaces", headers=headers(leader))).json()
    info = next(i for i in listing["interfaces"] if i["name"] == "demo_feature")
    source = git_repo / info["file_path"]
    source.write_text(
        "async def demo_feature(value: int = 1) -> int:\n    return value\n", encoding="utf-8"
    )
    assert (
        await client.post("/api/projects/p_demo/interfaces/refresh", headers=headers(leader))
    ).status_code == 200
    history = (
        await client.get(
            f"/api/interfaces/{info['interface_id']}/versions", headers=headers(leader)
        )
    ).json()
    assert [v["version"] for v in history["versions"]] == [1, 2]
    markdown = await client.get(
        "/api/projects/p_demo/interfaces?format=markdown", headers=headers(leader)
    )
    assert "版本历史与开发记录" in markdown.text
    assert "async def demo_feature" in markdown.text
    replan = await client.post(
        "/api/projects/p_demo/requirements",
        headers=headers(leader),
        json={
            "requirements": "在线商城：用户管理、商品管理、订单管理，"
            "新增优惠券功能，订单支持优惠券抵扣",
            "mode": "replan",
        },
    )
    assert replan.status_code == 200, replan.text
    assert replan.json()["version"] == 2
    assert replan.json()["diff"]["added_tasks"]
    after = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()[
        "tasks"
    ]
    assert next(t for t in after if t["task_id"] == task_id)["status"] == "completed"


async def test_project_namespacing_and_member_invitation(client, classroom, git_repo):
    leader, member_b, _ = classroom
    project = await client.post(
        "/api/projects",
        headers=headers(leader),
        json={"name": "Second", "repo_path": str(git_repo)},
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    second = {"token": project.json()["token"]}
    planned = await client.post(
        f"/api/projects/{project_id}/requirements",
        headers=headers(second),
        json={"requirements": "商城用户管理、商品管理、订单管理"},
    )
    assert planned.status_code == 200, planned.text
    first_ids = {
        t["task_id"]
        for t in (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()[
            "tasks"
        ]
    }
    second_ids = {
        t["task_id"]
        for t in (
            await client.get(f"/api/projects/{project_id}/tasks", headers=headers(second))
        ).json()["tasks"]
    }
    assert first_ids.isdisjoint(second_ids)
    assert (
        await client.get(f"/api/projects/{project_id}/tasks", headers=headers(leader))
    ).status_code == 403
    assert (
        await client.post(
            "/api/projects/p_demo/members", headers=headers(member_b), json={"name": "new"}
        )
    ).status_code == 403
    invited = await client.post(
        "/api/projects/p_demo/members", headers=headers(leader), json={"name": "new"}
    )
    assert invited.status_code == 200
    assert (
        await client.get("/api/projects/p_demo/interfaces", headers=headers(invited.json()))
    ).status_code == 200


async def test_unauthorized_changes_are_rejected_by_b(client, classroom):
    leader = classroom[0]
    task = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()[
        "tasks"
    ][0]
    response = await client.post(
        f"/api/tasks/{task['task_id']}/run",
        headers=headers(leader),
        json={"context": {"write_files": {"outside_allowed.py": "def wrong(): ...\n"}}},
    )
    assert response.status_code == 200, response.text
    result = await terminal(client, task["task_id"], leader)
    assert result["status"] == "failed"
    assert result["rejected_paths"] == ["outside_allowed.py"]
    merge = await client.post(
        f"/api/projects/p_demo/tasks/{task['task_id']}/merge", json={}, headers=headers(leader)
    )
    assert merge.status_code == 409


async def test_model_document_and_staleness(client, classroom, monkeypatch, git_repo):
    from app.interface_registry import documentation

    leader = classroom[0]
    missing = await client.post("/api/projects/p_demo/documentation", headers=headers(leader))
    assert missing.status_code == 409
    monkeypatch.setenv("TEAMCODE_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TEAMCODE_LLM_API_KEY", "test-only-key")
    monkeypatch.setenv("TEAMCODE_LLM_MODEL", "test-model")
    calls = []

    def fake_model(payload):
        calls.append(payload)
        return "## 模块说明\n用户模块维护用户查询；新增参数改变调用约定。"

    monkeypatch.setattr(documentation, "call_model", fake_model)
    generated = await client.post("/api/projects/p_demo/documentation", headers=headers(leader))
    assert generated.status_code == 200, generated.text
    assert calls and "history" in calls[0]["messages"][0]["content"]
    assert generated.json()["source"] == "model"
    current = (
        await client.get("/api/projects/p_demo/documentation", headers=headers(leader))
    ).json()
    assert current["stale"] is False
    (git_repo / "new_api.py").write_text("def added(): ...\n", encoding="utf-8")
    await client.post("/api/projects/p_demo/interfaces/refresh", headers=headers(leader))
    current = (
        await client.get("/api/projects/p_demo/documentation", headers=headers(leader))
    ).json()
    assert current["stale"] is True
    exported = await client.get(
        "/api/projects/p_demo/interfaces?format=markdown", headers=headers(leader)
    )
    assert "代码已变化" in exported.text and "用户模块维护用户查询" in exported.text


def test_import_call_dependencies(tmp_path):
    from app.interface_registry.extractor import extract_project

    (tmp_path / "orders.py").write_text(
        "from users import get_user\nimport products as p\n"
        "def checkout(uid):\n    get_user(uid)\n    return p.list_products()\n",
        encoding="utf-8",
    )
    info = extract_project(tmp_path, "p").interfaces[0]
    assert info.dependencies == ["products.list_products", "users.get_user"]


async def test_pause_resume_terminate_use_b_adapter(client, classroom, monkeypatch):
    leader = classroom[0]
    monkeypatch.setenv("TEAMCODE_MOCK_DELAY", "0.5")
    task = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()[
        "tasks"
    ][0]
    path = f"/api/tasks/{task['task_id']}"
    assert (await client.post(path + "/run", json={}, headers=headers(leader))).status_code == 200
    for _ in range(100):
        status = (await client.get(path + "/status", headers=headers(leader))).json()
        if status.get("session_id"):
            break
        await asyncio.sleep(0.02)
    paused = await client.post(path + "/pause", json={}, headers=headers(leader))
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    assert (await client.post(path + "/resume", json={}, headers=headers(leader))).json()[
        "status"
    ] == "running"
    assert (
        await client.post(path + "/terminate", json={}, headers=headers(leader))
    ).status_code == 200
    assert (await terminal(client, task["task_id"], leader))["status"] == "terminated"


async def test_cli_process_adapter(client, classroom, monkeypatch):
    import json
    import sys

    leader = classroom[0]
    task = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()[
        "tasks"
    ][0]
    target = task["allowed_paths"][0].rstrip("/") + "/from_cli.py"
    script = (
        f"import sys; assert '任务 ID：{task['task_id']}' in sys.argv[1]; "
        f"from pathlib import Path; p=Path({target!r}); "
        "p.parent.mkdir(parents=True,exist_ok=True); "
        "p.write_text('def from_cli(): return 7\\n'); print('CLI process completed')"
    )
    monkeypatch.setenv(
        "TEAMCODE_AGENTS",
        json.dumps(
            {"local-test-cli": {"command": [sys.executable, "-c", script], "prompt_mode": "arg"}}
        ),
    )
    response = await client.post(
        f"/api/tasks/{task['task_id']}/run",
        headers=headers(leader),
        json={"agent_name": "local-test-cli"},
    )
    assert response.status_code == 200, response.text
    result = await terminal(client, task["task_id"], leader)
    assert result["status"] == "succeeded", result
    logs = (await client.get(f"/api/tasks/{task['task_id']}/logs", headers=headers(leader))).json()[
        "logs"
    ]
    assert any("CLI process completed" in log["message"] for log in logs)


async def test_automatic_model_notes_after_scan(client, classroom, monkeypatch, git_repo):
    from app.interface_registry import documentation

    leader = classroom[0]
    for key, value in {
        "TEAMCODE_LLM_AUTO": "1",
        "TEAMCODE_LLM_BASE_URL": "https://example.invalid/v1",
        "TEAMCODE_LLM_API_KEY": "test-only",
        "TEAMCODE_LLM_MODEL": "test-model",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(documentation, "call_model", lambda payload: "自动生成的模块与变更说明")
    (git_repo / "automatic.py").write_text("def auto_documented(): ...\n", encoding="utf-8")
    await client.post("/api/projects/p_demo/interfaces/refresh", headers=headers(leader))
    for _ in range(100):
        state = (
            await client.get("/api/projects/p_demo/documentation", headers=headers(leader))
        ).json()
        if state["document"] and not state["stale"]:
            break
        await asyncio.sleep(0.02)
    assert state["document"]["markdown"] == "自动生成的模块与变更说明"


async def test_unaffected_running_tasks_continue_during_replanning(client, classroom, monkeypatch):
    leader = classroom[0]
    monkeypatch.setenv("TEAMCODE_MOCK_DELAY", "0.5")
    rows = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()["tasks"]
    product = next(t for t in rows if "product" in t["task_id"])
    await client.post(f"/api/tasks/{product['task_id']}/run", headers=headers(leader), json={})
    updated = await client.post(
        "/api/projects/p_demo/requirements",
        headers=headers(leader),
        json={
            "requirements": "在线商城：用户管理、商品管理、订单管理，"
            "新增优惠券功能，订单支持优惠券抵扣",
            "mode": "replan",
        },
    )
    assert updated.status_code == 200, updated.text
    rows = (await client.get("/api/projects/p_demo/tasks", headers=headers(leader))).json()["tasks"]
    assert next(t for t in rows if t["task_id"] == product["task_id"])["status"] == "in_progress"
    assert (await terminal(client, product["task_id"], leader))["status"] == "succeeded"
