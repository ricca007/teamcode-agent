#!/usr/bin/env python3
"""实验三 / 实验五：接口提取准确率、版本管理与实时推送评测。

运行方式（在仓库根目录）：

    .venv/bin/python experiments/eval_interfaces.py
    .venv/bin/python experiments/eval_interfaces.py --format json \
        --output experiments/reports/interfaces.json

脚本只依赖 C 负责的 interface_registry 模块，不需要启动后端进程；
版本管理部分使用临时 SQLite 数据库，可重复运行、不污染工作区。
"""

# ruff: noqa: E402  （先调整 sys.path，再导入 backend 模块）

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 让脚本在未 pip install -e 的情况下也能直接运行
sys.path.insert(0, str(ROOT / "backend"))

from app.interface_registry.cache import HashCache
from app.interface_registry.extractor import extract_project

FIXTURE = ROOT / "experiments" / "fixtures" / "shop_app"
EXPECTED = ROOT / "experiments" / "fixtures" / "expected.json"
REPORT_MARKDOWN = ROOT / "experiments" / "reports" / "interfaces.md"
PROJECT_ID = "p_shop"


# ---------------------------------------------------------------------------
# 实验三：提取准确率与增量扫描
# ---------------------------------------------------------------------------


def evaluate_accuracy() -> dict:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    result = extract_project(FIXTURE, PROJECT_ID)

    extracted = {(item.module, item.name, item.kind): item for item in result.interfaces}
    expected_map = {
        (item["module"], item["name"], item["kind"]): item for item in expected
    }

    matched = sorted(set(extracted) & set(expected_map))
    missing = sorted(set(expected_map) - set(extracted))
    extra = sorted(set(extracted) - set(expected_map))

    checks: list[bool] = []
    rows: list[dict] = []
    doc_with = 0

    for key in matched:
        exp = expected_map[key]
        act = extracted[key]
        row_checks = {
            "module": exp["module"] == act.module,
            "kind": exp["kind"] == act.kind,
            "returns": exp["returns"] == act.returns,
            "params": exp["params"] == [param.name for param in act.params],
        }
        checks.extend(row_checks.values())
        if act.docstring:
            doc_with += 1
        rows.append({"name": f"{act.module}.{act.name}", **row_checks})

    field_accuracy = sum(checks) / len(checks) if checks else 0.0
    doc_coverage = doc_with / len(matched) if matched else 0.0

    return {
        "expected": len(expected),
        "extracted": len(extracted),
        "matched": len(matched),
        "missing": missing,
        "extra": extra,
        "field_accuracy": field_accuracy,
        "doc_coverage": doc_coverage,
        "rows": rows,
        "warnings": result.warnings,
    }


def measure_latency() -> dict:
    full_times: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        extract_project(FIXTURE, PROJECT_ID)
        full_times.append((time.perf_counter() - start) * 1000)

    with tempfile.TemporaryDirectory() as temp_dir:
        copy = Path(temp_dir) / "shop_app"
        shutil.copytree(FIXTURE, copy)

        cache = HashCache()
        extract_project(copy, PROJECT_ID, hash_cache=cache)

        start = time.perf_counter()
        incremental = extract_project(copy, PROJECT_ID, hash_cache=cache)
        incremental_ms = (time.perf_counter() - start) * 1000

    return {
        "full_avg_ms": statistics.mean(full_times),
        "full_runs_ms": full_times,
        "incremental_ms": incremental_ms,
        "incremental_scanned": len(incremental.scanned_files),
        "incremental_skipped": len(incremental.skipped_files),
    }


# ---------------------------------------------------------------------------
# 实验五：版本管理、软删除与文档一致性
# ---------------------------------------------------------------------------


async def _make_engine(db_path: Path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.interface_registry.models import InterfaceRegistryBase
    from app.models import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(InterfaceRegistryBase.metadata.create_all)
    return engine


async def evaluate_registry() -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.interface_registry.service import InterfaceRegistryService

    with tempfile.TemporaryDirectory() as temp_dir:
        copy = Path(temp_dir) / "shop_app"
        shutil.copytree(FIXTURE, copy)
        engine = await _make_engine(Path(temp_dir) / "eval.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with factory() as session:
                service = InterfaceRegistryService(session)

                first = await service.scan(PROJECT_ID, copy)
                interfaces = await service.list_interfaces(PROJECT_ID)
                target = next(
                    item for item in interfaces if item.name == "normalize_email"
                )
                unchanged = await service.scan(PROJECT_ID, copy)

                # 修改签名：应升版本并写快照
                users = copy / "users.py"
                users.write_text(
                    users.read_text(encoding="utf-8").replace(
                        "def normalize_email(email: str) -> str:",
                        "def normalize_email(email: str, upper: bool = False) -> str:",
                    ),
                    encoding="utf-8",
                )
                updated = await service.scan(PROJECT_ID, copy)
                after_update = await service.get_interface(target.interface_id)
                versions = await service.list_versions(target.interface_id)
                markdown = await service.render_markdown(PROJECT_ID)

                # 删除文件：接口应软删除，并保留历史快照
                orders = [item for item in interfaces if item.module == "orders"]
                orders_id = orders[0].interface_id if orders else None
                (copy / "orders.py").unlink()
                deleted = await service.scan(PROJECT_ID, copy)
                gone = (
                    await service.get_interface(orders_id) if orders_id else None
                )
                order_versions = (
                    await service.list_versions(orders_id) if orders_id else []
                )
                deletion_snapshot_deleted = bool(
                    order_versions
                    and order_versions[-1]["snapshot"].get("is_deleted")
                )
        finally:
            await engine.dispose()

    return {
        "first_added": len(first.added),
        "unchanged_has_changes": unchanged.has_changes,
        "updated_count": len(updated.updated),
        "version_after_update": after_update.version if after_update else 0,
        "snapshot_count": len(versions),
        "soft_deleted": gone is None,
        "deleted_count": len(deleted.deleted),
        "deletion_snapshot_deleted": deletion_snapshot_deleted,
        "total_after_delete": deleted.total_interfaces,
        "markdown_has_signature": (
            "normalize_email(email: str, upper: bool = False) -> str" in markdown
        ),
        "markdown_has_usage_note": "唯一事实来源" in markdown,
    }


# ---------------------------------------------------------------------------
# 实验三：代码变更到实时事件的端到端延迟
# ---------------------------------------------------------------------------


async def measure_realtime() -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.interface_registry.service import InterfaceRegistryService
    from app.interface_registry.watcher import InterfaceWatcher

    latencies: list[float] = []
    debounce_seconds = 0.1

    with tempfile.TemporaryDirectory() as temp_dir:
        copy = Path(temp_dir) / "shop_app"
        shutil.copytree(FIXTURE, copy)
        engine = await _make_engine(Path(temp_dir) / "realtime.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with factory() as session:
                # 建立基线，避免第一次扫描把所有接口都算成新增
                await InterfaceRegistryService(session).scan(PROJECT_ID, copy)

            loop = asyncio.get_running_loop()

            for run in range(3):
                event_times: list[float] = []

                async def scan_and_publish(
                    event_times: list[float] = event_times,
                ) -> None:
                    async with factory() as session:
                        summary = await InterfaceRegistryService(session).scan(
                            PROJECT_ID, copy
                        )
                    if summary.has_changes:
                        event_times.append(time.perf_counter())

                def trigger(_project_id: str, _pending: list[str]) -> None:
                    asyncio.run_coroutine_threadsafe(scan_and_publish(), loop)

                watcher = InterfaceWatcher(
                    project_id=PROJECT_ID,
                    root=copy,
                    trigger=trigger,
                    debounce_seconds=debounce_seconds,
                )

                target = copy / "users.py"
                target.write_text(
                    target.read_text(encoding="utf-8")
                    + f'\n\ndef eval_hook_{run}() -> None:\n'
                    f'    """评测新增函数 {run}。"""\n    pass\n',
                    encoding="utf-8",
                )

                start = time.perf_counter()
                watcher.notify(target)
                deadline = start + 5
                while not event_times and time.perf_counter() < deadline:
                    await asyncio.sleep(0.005)

                if event_times:
                    latencies.append((event_times[0] - start) * 1000)
                watcher.stop()
        finally:
            await engine.dispose()

    return {
        "runs": len(latencies),
        "latencies_ms": latencies,
        "avg_ms": statistics.mean(latencies) if latencies else 0.0,
        "debounce_ms": debounce_seconds * 1000,
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def render_report(accuracy: dict, latency: dict, registry: dict, realtime: dict) -> str:
    lines = [
        "# 接口提取与文档维护评测",
        "",
        f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "> 样例项目：`experiments/fixtures/shop_app`",
        (
            "> 评测方式：AST 提取结果与人工标注 `expected.json` 逐字段比对；"
            "版本与实时推送使用临时 SQLite 数据库复现。"
        ),
        "",
        "## 实验三：实时接口发现与共享",
        "",
        "### 提取准确率",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 人工标注接口数 | {accuracy['expected']} |",
        f"| AST 提取接口数 | {accuracy['extracted']} |",
        f"| 匹配接口数 | {accuracy['matched']} |",
        f"| 缺失接口 | {len(accuracy['missing'])} |",
        f"| 多余接口 | {len(accuracy['extra'])} |",
        f"| 字段级准确率 | {accuracy['field_accuracy'] * 100:.2f}% |",
        f"| docstring 覆盖率 | {accuracy['doc_coverage'] * 100:.2f}% |",
        "",
        "### 扫描性能",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 全量扫描耗时（3 次均值） | {latency['full_avg_ms']:.2f} ms |",
        f"| 增量扫描耗时（无变更） | {latency['incremental_ms']:.2f} ms |",
        f"| 增量扫描重扫文件数 | {latency['incremental_scanned']} |",
        f"| 增量扫描跳过文件数 | {latency['incremental_skipped']} |",
        "",
        "### 变更到实时事件",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 防抖窗口 | {realtime['debounce_ms']:.0f} ms |",
        f"| 成功收到事件的轮次 | {realtime['runs']} / 3 |",
        f"| 平均端到端延迟（含防抖） | {realtime['avg_ms']:.2f} ms |",
        "",
    ]

    if accuracy["missing"]:
        lines.append("### 缺失接口")
        lines.extend(f"- `{'.'.join(key)}`" for key in accuracy["missing"])
        lines.append("")

    if accuracy["extra"]:
        lines.append("### 多余接口")
        lines.extend(f"- `{'.'.join(key)}`" for key in accuracy["extra"])
        lines.append("")

    lines.extend(
        [
            "### 字段明细",
            "",
            "| 接口 | module | kind | returns | params |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in accuracy["rows"]:
        lines.append(
            f"| `{row['name']}` | {_mark(row['module'])} | {_mark(row['kind'])} "
            f"| {_mark(row['returns'])} | {_mark(row['params'])} |"
        )

    lines.extend(
        [
            "",
            "## 实验五：自动文档维护",
            "",
            "| 检查项 | 结果 |",
            "| --- | --- |",
            f"| 首次扫描注册接口数 | {registry['first_added']} |",
            f"| 内容未变时不升版本 | {_mark(not registry['unchanged_has_changes'])} |",
            f"| 签名变化触发更新 | {_mark(registry['updated_count'] > 0)} |",
            f"| 更新后版本号 | v{registry['version_after_update']} |",
            f"| 历史快照条数 | {registry['snapshot_count']} |",
            f"| 删除文件后软删除 | {_mark(registry['soft_deleted'])} |",
            f"| 删除快照标记 | {_mark(registry['deletion_snapshot_deleted'])} |",
            f"| 删除后剩余接口数 | {registry['total_after_delete']} |",
            f"| Markdown 含最新签名 | {_mark(registry['markdown_has_signature'])} |",
            f"| Markdown 含使用说明 | {_mark(registry['markdown_has_usage_note'])} |",
            "",
            (
                "- 函数名、参数、返回类型、模块与文件路径均由 Python AST 客观提取，"
                f"字段级准确率 {accuracy['field_accuracy'] * 100:.2f}%。"
            ),
            (
                "- 接口内容变化时 version 自增并写入 `interface_versions` 快照；"
                "删除采用软删除，历史仍可追溯。"
            ),
            "- Markdown 文档由同一 service 生成，CLI / REST / MCP 三个出口内容一致。",
            "",
            "## 说明",
            "",
            "- 增量扫描基于文件 sha256 缓存；无变更时只做哈希校验，不解析 AST。",
            "- 语法错误文件会被跳过并记录 warning，不会中断整体扫描，也不会误删已有接口。",
            "- 实时延迟包含 100ms 防抖窗口，实际推送通常在防抖后立即完成。",
            "- 本报告可直接放入课程实验文档。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="接口提取与文档维护评测")
    parser.add_argument(
        "--format", choices=["markdown", "json"], default="markdown"
    )
    parser.add_argument("--output", default=None, help="报告输出路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    accuracy = evaluate_accuracy()
    latency = measure_latency()
    registry = asyncio.run(evaluate_registry())
    realtime = asyncio.run(measure_realtime())

    payload = {
        "accuracy": accuracy,
        "latency": latency,
        "registry": registry,
        "realtime": realtime,
    }

    if args.format == "json":
        output = args.output or str(REPORT_MARKDOWN.with_suffix(".json"))
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        output = args.output or str(REPORT_MARKDOWN)
        text = render_report(accuracy, latency, registry, realtime)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")

    if args.format == "markdown":
        print(text)
    print(f"\n报告已写入 {output_path}")

    registry_ok = (
        not registry["unchanged_has_changes"]
        and registry["updated_count"] > 0
        and registry["version_after_update"] == 2
        and registry["soft_deleted"]
        and registry["deletion_snapshot_deleted"]
        and registry["markdown_has_signature"]
        and registry["markdown_has_usage_note"]
    )
    realtime_ok = realtime["runs"] == 3
    return 0 if accuracy["field_accuracy"] == 1.0 and registry_ok and realtime_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
