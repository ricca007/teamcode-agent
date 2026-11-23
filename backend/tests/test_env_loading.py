"""`.env` 加载语义：未传的环境变量从 .env 补，已传的优先。"""

from __future__ import annotations

import os

from app.config import load_env_files


def test_env_file_fills_missing_and_preserves_explicit(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TEAMCODE_TEST_AGENT=codex\n"
        "TEAMCODE_TEST_SECRET=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEAMCODE_ENV_FILE", str(env_file))
    monkeypatch.delenv("TEAMCODE_TEST_AGENT", raising=False)
    monkeypatch.setenv("TEAMCODE_TEST_SECRET", "explicit")

    try:
        load_env_files()
        # 未显式传入 → 从 .env 读
        assert os.environ["TEAMCODE_TEST_AGENT"] == "codex"
        # 已显式传入 → 不被 .env 覆盖
        assert os.environ["TEAMCODE_TEST_SECRET"] == "explicit"
    finally:
        os.environ.pop("TEAMCODE_TEST_AGENT", None)
