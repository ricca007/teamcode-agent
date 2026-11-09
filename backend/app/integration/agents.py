"""可配置的 Coding Agent 注册表。

默认支持：
- claude：Claude Code，使用流式包装器（支持实时日志、sandbox、会话续聊）；
- codex：OpenAI Codex CLI，`codex exec <prompt>`；
- aider：Aider，`aider --message <prompt>`；
- mock：测试/演示；
- dsh / 其它：通过 ``TEAMCODE_AGENTS`` JSON 或 ``TEAMCODE_DSH_COMMAND`` 配置。

每个成员可以在前端选择自己的 Agent；选择只影响请求里使用的命令，
任务权限（owner/leader + allowed_paths）不变。
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    command: tuple[str, ...] | None
    prompt_mode: str = "stdin"
    kind: str = "cli"  # claude-stream | cli | mock
    binary: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def claude_wrapper_path() -> Path:
    return _repo_root() / "scripts" / "claude_stream_wrapper.py"


def generic_wrapper_path() -> Path:
    return _repo_root() / "scripts" / "agent_cli_wrapper.py"


def _default_claude() -> AgentSpec:
    raw = os.getenv("TEAMCODE_AGENT_COMMAND", "").strip()
    command = (
        tuple(shlex.split(raw))
        if raw
        else (sys.executable, str(claude_wrapper_path()))
    )
    return AgentSpec(
        name="claude",
        command=command,
        prompt_mode=os.getenv("TEAMCODE_AGENT_PROMPT_MODE", "stdin"),
        kind="claude-stream",
        binary="claude",
    )


def _from_env_command(
    env_name: str, default: str, *, name: str, prompt_mode: str
) -> AgentSpec:
    raw = os.getenv(env_name, default).strip()
    return AgentSpec(
        name=name,
        command=tuple(shlex.split(raw)),
        prompt_mode=prompt_mode,
        kind="cli",
        binary=shlex.split(raw)[0] if raw else name,
    )


def agent_specs() -> dict[str, AgentSpec]:
    specs: dict[str, AgentSpec] = {
        "claude": _default_claude(),
        "codex": _from_env_command(
            "TEAMCODE_CODEX_COMMAND",
            "codex exec",
            name="codex",
            prompt_mode=os.getenv("TEAMCODE_CODEX_PROMPT_MODE", "arg"),
        ),
        "aider": _from_env_command(
            "TEAMCODE_AIDER_COMMAND",
            "aider --message",
            name="aider",
            prompt_mode=os.getenv("TEAMCODE_AIDER_PROMPT_MODE", "arg"),
        ),
        "mock": AgentSpec(name="mock", command=None, kind="mock"),
    }

    dsh_command = os.getenv("TEAMCODE_DSH_COMMAND", "").strip()
    if dsh_command:
        specs["dsh"] = AgentSpec(
            name="dsh",
            command=tuple(shlex.split(dsh_command)),
            prompt_mode=os.getenv("TEAMCODE_DSH_PROMPT_MODE", "arg"),
            kind="cli",
            binary=shlex.split(dsh_command)[0],
        )

    raw = os.getenv("TEAMCODE_AGENTS", "").strip()
    if raw:
        try:
            overrides = json.loads(raw)
            if not isinstance(overrides, dict):
                raise ValueError("TEAMCODE_AGENTS 必须是 JSON 对象")
            for name, value in overrides.items():
                if not isinstance(value, dict) or not value.get("command"):
                    continue
                command = tuple(shlex.split(str(value["command"])))
                specs[str(name)] = AgentSpec(
                    name=str(name),
                    command=command,
                    prompt_mode=str(value.get("prompt_mode", "arg")),
                    kind=str(value.get("kind", "cli")),
                    binary=str(value.get("binary") or command[0]),
                )
        except Exception:
            logger.exception("解析 TEAMCODE_AGENTS 失败，使用默认 Agent 列表")

    return specs


def get_agent_spec(name: str | None) -> AgentSpec | None:
    if not name:
        return None
    return agent_specs().get(name)


def list_agents() -> list[dict[str, object]]:
    """产品界面展示的 Agent 列表；mock 默认不暴露，仅测试可用。"""
    include_mock = os.getenv("TEAMCODE_EXPOSE_MOCK", "0") == "1"
    available: list[dict[str, object]] = []
    for spec in agent_specs().values():
        if spec.kind == "mock":
            if not include_mock:
                continue
            is_available = True
        else:
            binary = spec.binary or (
                spec.command[0] if spec.command else None
            )
            is_available = bool(
                binary and (shutil.which(binary) or Path(binary).exists())
            )
        available.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "prompt_mode": spec.prompt_mode,
                "available": is_available,
            }
        )
    return sorted(available, key=lambda item: str(item["name"]))
