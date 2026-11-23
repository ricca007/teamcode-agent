from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_candidates() -> list[Path]:
    """按优先级返回可能的 `.env` 路径。"""
    explicit = os.getenv("TEAMCODE_ENV_FILE", "").strip()
    if explicit:
        return [Path(explicit)]
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env",
        here.parents[1] / ".env",  # backend/.env
        here.parents[2] / ".env",  # repo root .env
    ]
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def load_env_files() -> None:
    """把 `.env` 读进进程环境，但**不覆盖已存在的环境变量**。

    语义：显式传入的环境变量优先，没传的才从 .env 读；也让
    ``os.getenv("TEAMCODE_*")`` 这类读取能拿到 .env 里的值。
    """
    for path in _env_candidates():
        if path.is_file():
            load_dotenv(path, override=False)


# 在 Settings / 其它模块读取环境变量之前先加载 .env
load_env_files()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TeamCode Agent API"
    database_url: str = "postgresql+asyncpg://teamcode:teamcode@localhost:5432/teamcode"


@lru_cache
def get_settings() -> Settings:
    return Settings()
