"""启动鉴权配置校验的回归测试（P0-2）。"""

from __future__ import annotations

import pytest

from app.integration.auth import DEFAULT_AUTH_SECRET, auth_secret, validate_auth_config


def test_requires_secret_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    monkeypatch.delenv("TEAMCODE_AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        validate_auth_config()


def test_rejects_default_secret(monkeypatch):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TEAMCODE_AUTH_SECRET", DEFAULT_AUTH_SECRET)
    with pytest.raises(RuntimeError):
        auth_secret()


def test_accepts_explicit_secret(monkeypatch):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("TEAMCODE_AUTH_SECRET", "x" * 48)
    validate_auth_config()
    assert auth_secret() == "x" * 48


def test_auth_disabled_allows_default(monkeypatch):
    monkeypatch.setenv("TEAMCODE_REQUIRE_AUTH", "0")
    monkeypatch.delenv("TEAMCODE_AUTH_SECRET", raising=False)
    validate_auth_config()
    assert auth_secret() == DEFAULT_AUTH_SECRET
