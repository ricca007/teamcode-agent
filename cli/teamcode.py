"""C-3：``teamcode pull-interfaces`` 命令行工具。

设计原则：
- 默认走 REST（与前端、其他成员使用同一出口）；
- ``--offline`` 直接读数据库，适合没有后端进程的开发环境；
- 只依赖标准库 urllib，避免给 CLI 引入额外 HTTP 依赖；
- 生成的文档开头明确声明「唯一事实来源」，提示 Coding Agent 不要猜接口。

适配说明：
A 的后端使用 async SQLAlchemy，因此离线模式也走异步引擎，并在连接失败时
自动回退到本地 SQLite（降级信息打印到 stderr，不会静默发生）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from cli.logging_setup import configure_cli_logging

logger = logging.getLogger("teamcode.cli")

DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_FALLBACK_DATABASE_URL = "sqlite+aiosqlite:///./teamcode.db"


class CliError(Exception):
    """可预期的用户级错误（不打印 traceback）。"""


# ---------------------------------------------------------------------------
# 远程 / 离线两种数据源
# ---------------------------------------------------------------------------


def pull_remote(
    api_base: str,
    project_id: str,
    fmt: str,
    *,
    timeout: float = 10.0,
    api_key: str | None = None,
) -> str:
    url = (
        f"{api_base.rstrip('/')}/api/projects/{quote(project_id, safe='')}"
        f"/interfaces?{urlencode({'format': fmt})}"
    )
    logger.info(
        "在线拉取接口: project=%s format=%s api=%s key=%s",
        project_id,
        fmt,
        api_base,
        "yes" if api_key else "no",
    )
    request = Request(url)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        message = _extract_error_message(raw)
        raise CliError(f"请求失败（HTTP {exc.code}）：{message}") from exc
    except URLError as exc:
        raise CliError(f"无法连接后端 {api_base}：{exc.reason}") from exc

    if fmt == "json":
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CliError("后端返回的不是合法 JSON") from exc
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return body


def pull_offline(
    project_id: str,
    fmt: str,
    *,
    db_url: str | None = None,
    fallback_db_url: str | None = None,
) -> str:
    return asyncio.run(
        _pull_offline_async(
            project_id,
            fmt,
            db_url=db_url,
            fallback_db_url=fallback_db_url,
        )
    )


async def _pull_offline_async(
    project_id: str,
    fmt: str,
    *,
    db_url: str | None,
    fallback_db_url: str | None,
) -> str:
    # 延迟导入：纯在线模式下即使没有装 SQLAlchemy 也不影响 CLI 启动
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.config import get_settings
    from app.interface_registry.schemas import InterfaceListResponse, utcnow
    from app.interface_registry.service import InterfaceRegistryService
    from app.models.project import Project

    settings = get_settings()
    requested = db_url or settings.database_url
    fallback = (
        fallback_db_url
        or os.getenv("FALLBACK_DATABASE_URL")
        or DEFAULT_FALLBACK_DATABASE_URL
    )

    engine = None
    try:
        try:
            engine = await _connect_engine(requested)
        except Exception as exc:
            if _backend_name(requested) == "sqlite" or requested == fallback:
                raise
            # 降级必须在 CLI 可见，不能静默切换数据库
            logger.warning(
                "降级提示：%s 不可用（%s: %s）；当前使用 %s",
                _backend_name(requested),
                type(exc).__name__,
                exc,
                mask_url(fallback),
            )
            engine = await _connect_engine(fallback)

        logger.info(
            "离线读取接口: project=%s format=%s db=%s",
            project_id,
            fmt,
            mask_url(str(engine.url)),
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = InterfaceRegistryService(session)
            project = await session.get(Project, project_id)
            interfaces = await service.list_interfaces(project_id)

            # 离线模式也要给出清晰的非法 project id 报错
            if project is None and not interfaces:
                raise CliError(f"项目不存在：{project_id}")

            if fmt == "markdown":
                return await service.render_markdown(project_id)

            payload = InterfaceListResponse(
                project_id=project_id,
                generated_at=utcnow(),
                count=len(interfaces),
                interfaces=interfaces,
            )
            return json.dumps(
                payload.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
    finally:
        if engine is not None:
            await engine.dispose()


async def _connect_engine(url: str):
    """创建异步引擎并确保公共表与 C 的扩展表都存在。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.interface_registry.logging_setup import configure_logging
    from app.interface_registry.models import InterfaceRegistryBase
    from app.models import Base

    configure_logging()

    async_url = _to_async_url(url)
    connect_args = {}
    if _backend_name(async_url) in {"postgresql", "postgres"}:
        # 不要在 PostgreSQL 不可用时卡住 CLI
        connect_args["timeout"] = 3

    engine = create_async_engine(
        async_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
    except Exception:
        await engine.dispose()
        raise
    return engine


def _to_async_url(url: str) -> str:
    """把同步风格的连接串转换为 async SQLAlchemy 可用的形式。"""
    url = url.strip()
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite://") :]
    if url.startswith("sqlite+aiosqlite://"):
        return url
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            rest = url.split("://", 1)[1]
            return "postgresql+asyncpg://" + rest
    return url


def _backend_name(url: str) -> str:
    scheme = urlsplit(url).scheme or "sqlite"
    return scheme.split("+", 1)[0]


def mask_url(url: str) -> str:
    """隐藏连接串里的密码，避免日志泄露凭据。"""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    user = parts.username or ""
    netloc = f"{user}:***@{host}"
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def _extract_error_message(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip() or "未知错误"
    if isinstance(payload, dict):
        return str(
            payload.get("message")
            or payload.get("detail")
            or payload.get("code")
            or raw
        )
    return raw


# ---------------------------------------------------------------------------
# 命令解析
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teamcode",
        description="TeamCode Agent 命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pull = subparsers.add_parser(
        "pull-interfaces",
        help="拉取项目接口文档（Markdown 或 JSON）",
        description=(
            "从 Interface Registry 拉取项目的最新接口文档。"
            "默认调用 REST 接口；--offline 时直接读取数据库。"
        ),
    )
    pull.add_argument("--project", required=True, help="项目 ID，例如 p_001")
    pull.add_argument(
        "--output",
        default=None,
        help="输出文件路径；不指定时打印到标准输出",
    )
    pull.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    pull.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help=f"后端地址（默认 {DEFAULT_API_BASE}）",
    )
    pull.add_argument(
        "--offline",
        action="store_true",
        help="不访问后端，直接从数据库读取",
    )
    pull.add_argument(
        "--db-url",
        default=None,
        help="--offline 时使用的数据库连接串（默认读取 DATABASE_URL）",
    )
    pull.add_argument(
        "--fallback-db-url",
        default=None,
        help="数据库不可用时回退到的连接串（默认读取 FALLBACK_DATABASE_URL）",
    )
    pull.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP 超时秒数（默认 10）",
    )
    pull.add_argument(
        "--api-key",
        default=os.getenv("TEAMCODE_API_KEY"),
        help="在线模式使用的 API Key（也可用环境变量 TEAMCODE_API_KEY）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_cli_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "pull-interfaces":  # pragma: no cover - argparse 已限制
        parser.print_help()
        return 1

    try:
        if args.offline:
            text = pull_offline(
                args.project,
                args.format,
                db_url=args.db_url,
                fallback_db_url=args.fallback_db_url,
            )
        else:
            text = pull_remote(
                args.api_base,
                args.project,
                args.format,
                timeout=args.timeout,
                api_key=args.api_key,
            )
    except CliError as exc:
        logger.error("错误：%s", exc)
        return 2
    except Exception:  # 数据库损坏、权限不足等离线故障
        logger.exception(
            "离线读取失败: project=%s format=%s", args.project, args.format
        )
        return 2

    if args.output:
        output_path = Path(args.output)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text, encoding="utf-8")
        except OSError:
            logger.exception("写入输出文件失败: %s", output_path)
            return 2
        logger.info("已写入 %s（%d 字符）", output_path, len(text))
        print(f"[teamcode] 已写入 {output_path}（{len(text)} 字符）")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
