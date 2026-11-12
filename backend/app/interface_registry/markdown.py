"""接口文档的 Markdown 渲染（纯函数，无副作用）。

REST / CLI / MCP 三个出口复用同一份渲染逻辑，避免文档格式各写一套。
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from app.interface_registry.schemas import InterfaceInfo


def format_signature(info: InterfaceInfo) -> str:
    """生成人类可读的函数签名。"""
    parts: list[str] = []
    keyword_separator = False
    for index, param in enumerate(info.params):
        if param.kind == "keyword_only" and not keyword_separator:
            parts.append("*")
            keyword_separator = True
        if param.name.startswith("*"):
            keyword_separator = True
        text = param.name
        if param.annotation:
            text += f": {param.annotation}"
        if param.default is not None:
            text += f" = {param.default}"
        parts.append(text)
        if param.kind == "positional_only" and (
            index + 1 == len(info.params) or info.params[index + 1].kind != "positional_only"
        ):
            parts.append("/")

    if info.kind == "class":
        prefix = "class "
    elif info.is_async:
        prefix = "async def "
    else:
        prefix = "def "

    signature = f"{prefix}{info.name}({', '.join(parts)})"
    if info.returns:
        signature += f" -> {info.returns}"
    return signature


def render_markdown(
    project_id: str,
    interfaces: list[InterfaceInfo],
    *,
    generated_at: datetime | None = None,
    history: list[dict] | None = None,
    semantic: dict | None = None,
) -> str:
    """渲染可直接交给 Coding Agent 阅读的接口文档。"""
    generated_at = generated_at or datetime.now(UTC)
    sorted_interfaces = sorted(
        interfaces,
        key=lambda i: (i.module, i.lineno or 0, i.name, i.kind),
    )

    version_counter = Counter(i.version for i in sorted_interfaces)
    version_summary = (
        ", ".join(f"v{version} × {count}" for version, count in sorted(version_counter.items()))
        or "无"
    )
    modules = sorted({i.module for i in sorted_interfaces})

    lines: list[str] = [
        "# TeamCode 接口文档",
        "",
        f"> 项目 ID：`{project_id}`  ",
        f"> 生成时间：{generated_at.isoformat()}  ",
        f"> 接口总数：{len(sorted_interfaces)}  |  模块数：{len(modules)}  |  "
        f"版本摘要：{version_summary}",
        "",
        "> **使用说明**：本文档由 Interface Registry 基于 Python AST 自动生成，"
        "是接口的唯一事实来源。Coding Agent 在开发前应以此文档为准，"
        "不要自行猜测接口名称、参数或返回类型。",
        "",
    ]

    if not sorted_interfaces:
        lines.append("_当前项目尚未注册任何接口。_")
        lines.append("")

    for module in modules:
        module_items = [i for i in sorted_interfaces if i.module == module]
        lines.append(f"## 模块 `{module}`")
        lines.append("")

        for info in module_items:
            lines.append(f"### `{info.name}`")
            lines.append("")
            lines.append("```python")
            lines.append(format_signature(info))
            lines.append("```")
            lines.append("")
            lines.append(f"- 类型：`{info.kind}`")
            lines.append(f"- ID：`{info.interface_id}`")
            lines.append(f"- 文件：`{info.file_path}`")
            lines.append(f"- 版本：`v{info.version}`")
            lines.append(
                "- 静态可解析调用依赖：" + (", ".join(f"`{d}`" for d in info.dependencies) or "无")
            )
            if info.commit_hash:
                lines.append(f"- 提交：`{info.commit_hash}`")
            if info.decorators:
                decorators = ", ".join(f"`@{d}`" for d in info.decorators)
                lines.append(f"- 装饰器：{decorators}")
            if info.docstring:
                lines.append("")
                lines.append(info.docstring.strip())
            lines.append("")

    if history:
        lines.extend(["## 版本历史与开发记录", ""])
        for snapshot in history:
            info = InterfaceInfo.model_validate(snapshot)
            action = "删除" if snapshot.get("is_deleted") else "注册/更新"
            lines.extend(
                [
                    f"- {info.name} · v{info.version} · {action}",
                    f"  - `{format_signature(info)}`",
                    f"  - commit: `{info.commit_hash or '未提交'}`",
                ]
            )
    if semantic:
        from app.interface_registry.documentation import revision

        stale = semantic.get("revision") != revision(interfaces)
        lines.extend(
            [
                "",
                "## Agent 语义说明",
                "",
                f"> 来源：{semantic.get('model')}；生成时间：{semantic.get('ts')}；"
                + ("代码已变化，请重新生成说明。" if stale else "与当前接口版本一致。"),
                "",
                semantic.get("markdown", ""),
            ]
        )
    return "\n".join(lines)
