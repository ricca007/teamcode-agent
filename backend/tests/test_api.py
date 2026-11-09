"""C-2 验收测试：REST 接口与错误格式。"""

from __future__ import annotations

import logging


async def test_interfaces_health(client):
    response = await client.get("/health/interfaces")
    assert response.status_code == 200
    body = response.json()
    assert "available" in body
    assert "watching" in body
    assert "degraded" in body


async def test_refresh_then_list_json(client):
    refresh = await client.post("/api/projects/p_test/interfaces/refresh")
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["added"]
    assert body["has_changes"] is True

    response = await client.get("/api/projects/p_test/interfaces")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "p_test"
    assert payload["count"] > 0
    names = {item["name"] for item in payload["interfaces"]}
    assert "UserService.get_user" in names
    assert "normalize_name" in names
    # C 扩展展示字段必须出现在 JSON 里
    assert "lineno" in payload["interfaces"][0]
    assert "is_async" in payload["interfaces"][0]


async def test_markdown_format(client):
    await client.post("/api/projects/p_test/interfaces/refresh")
    response = await client.get(
        "/api/projects/p_test/interfaces", params={"format": "markdown"}
    )
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "TeamCode 接口文档" in response.text
    assert "UserService.get_user" in response.text


async def test_interface_detail_and_not_found(client):
    await client.post("/api/projects/p_test/interfaces/refresh")
    listing = (await client.get("/api/projects/p_test/interfaces")).json()
    interface_id = listing["interfaces"][0]["interface_id"]

    detail = await client.get(f"/api/interfaces/{interface_id}")
    assert detail.status_code == 200
    assert detail.json()["interface_id"] == interface_id

    missing = await client.get("/api/interfaces/iface_not_exist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "interface_not_found"


async def test_list_unknown_project_returns_404(client):
    response = await client.get("/api/projects/p_missing/interfaces")
    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


async def test_refresh_unknown_project_returns_error_envelope(client):
    response = await client.post("/api/projects/p_missing/interfaces/refresh")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "project_not_found"
    assert "p_missing" in payload["message"]


async def test_refresh_with_invalid_root(client):
    response = await client.post(
        "/api/projects/p_test/interfaces/refresh",
        json={"root": "/path/does/not/exist"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "project_root_missing"


async def test_unexpected_scan_error_returns_500_envelope(client, monkeypatch, caplog):
    from app.interface_registry import service as service_module

    async def explode(_self, *_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        service_module.InterfaceRegistryService, "scan", explode
    )

    with caplog.at_level(logging.ERROR, logger="app.interface_registry.api"):
        response = await client.post(
            "/api/projects/p_test/interfaces/refresh"
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["code"] == "internal_error"
    assert "boom" not in payload["message"]  # 不向前端泄露内部异常
    assert "接口刷新失败" in caplog.text
