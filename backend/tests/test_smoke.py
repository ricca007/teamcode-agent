"""端到端冒烟测试：覆盖本轮 C 侧修复的关键链路。

用真实 Git 仓库 + ASGI 客户端跑通「建项目 → 规划 → 执行 → 日志 → 合并 →
清理」，并对鉴权配置、提取器、wrapper 沙箱决策做一次快速验证。
相比细粒度单测，这里只关心整体是否可用（一次失败即暴露回归）。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.integration.auth import DEFAULT_AUTH_SECRET, validate_auth_config
from app.integration.service import _runtimes

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENTS = "在线商城：用户管理、商品管理、订单管理、优惠券功能。"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _create_project(client, repo: Path) -> str:
    response = await client.post(
        "/api/projects",
        json={
            "name": "冒烟演示",
            "repo_path": str(repo),
            "owner_id": "u_lead",
            "owner_name": "Leader",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _plan(client, project_id: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "requirements": REQUIREMENTS,
            "members": [
                {"member_id": "u_a", "name": "成员 A", "areas": ["user"]},
                {"member_id": "u_b", "name": "成员 B", "areas": ["order", "coupon"]},
            ],
            "max_tasks": 4,
            "mode": "plan",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _first_task(client, project_id: str) -> dict:
    response = await client.get(f"/api/projects/{project_id}/tasks")
    assert response.status_code == 200, response.text
    return response.json()["tasks"][0]


async def _wait_terminal(client, task_id: str, timeout: float = 15.0) -> dict:
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


# ---------------------------------------------------------------------------
# 冒烟用例
# ---------------------------------------------------------------------------


def test_auth_config_smoke(monkeypatch):
    """开启鉴权时必须有非默认 secret；关闭鉴权时用 dev 默认值。"""
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TEAMCODE_AUTH_SECRET", DEFAULT_AUTH_SECRET)
    with pytest.raises(RuntimeError):
        validate_auth_config()

    monkeypatch.setenv("TEAMCODE_AUTH_SECRET", "smoke-" + "x" * 40)
    validate_auth_config()

    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "0")
    monkeypatch.delenv("TEAMCODE_AUTH_SECRET", raising=False)
    validate_auth_config()


async def test_end_to_end_run_logs_merge_cleanup(client, git_repo: Path):
    project_id = await _create_project(client, git_repo)
    await _plan(client, project_id)
    task = await _first_task(client, project_id)

    allowed = task["allowed_paths"][0].rstrip("/")
    target_path = f"{allowed}/smoke_feature.py"
    source = (
        "def smoke_feature() -> str:\n"
        '    """Smoke feature."""\n'
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

    # 日志：sequence 连续且 id 稳定，保证顺序不会因字符串排序而错乱
    logs_response = await client.get(f"/api/tasks/{task['task_id']}/logs")
    assert logs_response.status_code == 200, logs_response.text
    logs = logs_response.json()["logs"]
    assert logs, "expected at least one log line"
    sequences = [entry["sequence"] for entry in logs]
    assert sequences == list(range(1, len(logs) + 1))
    session_id = logs[0]["session_id"]
    assert logs[0]["id"] == f"log_{session_id}_{1:06d}"

    # 合并：清理 Worktree，响应字段正确
    workspace = Path(status["workspace"])
    assert workspace.is_dir()
    merged = await client.post(
        f"/api/projects/{project_id}/tasks/{task['task_id']}/merge",
        json={"message": "smoke merge"},
    )
    assert merged.status_code == 200, merged.text
    payload = merged.json()
    assert payload["workspace_cleaned"] is True
    assert payload["workspace_cleanup_error"] is None
    assert not workspace.exists()
    assert (git_repo / target_path).exists()

    # 再次合并：Worktree 已清理
    again = await client.post(
        f"/api/projects/{project_id}/tasks/{task['task_id']}/merge",
        json={"message": "smoke merge again"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "workspace_missing"

    assert project_id in _runtimes


def test_extractor_smoke(sample_project: Path):
    from app.interface_registry.extractor import extract_project

    names = {item.name for item in extract_project(sample_project, "p_smoke").interfaces}
    assert "normalize_name" in names
    assert "UserService.get_user._inner" not in names


def test_wrapper_sandbox_smoke():
    wrapper_path = REPO_ROOT / "scripts" / "claude_stream_wrapper.py"
    spec = importlib.util.spec_from_file_location("smoke_wrapper", wrapper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module._sandbox_decision("darwin", False, None, True).mode == "sandbox"
    assert module._sandbox_decision("linux", False, None, False).fatal is False
    assert module._sandbox_decision("linux", False, "1", False).fatal is True
