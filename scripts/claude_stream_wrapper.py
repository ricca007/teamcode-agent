#!/usr/bin/env python3
"""Claude Code 流式包装器。

作用：
- 从 stdin 读取 prompt（B 的 CLIAdapter 以 stdin 模式调用）；
- 启动 ``claude -p --output-format stream-json --verbose``；
- 把 JSON 事件解析成人类可读的日志行（思考心跳、工具调用、助手文本、结果）；
- 支持 ``--continue-session``：在同一工作目录继续最近的 Claude 会话，
  用于 Web 控制台里的「会话内对话」。

退出码：Claude 进程返回码；如果 result 事件标记失败，返回 1。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_ALLOWED_TOOLS = "Read Glob Grep LS Write Edit Bash"
DEFAULT_PERMISSION_MODE = "acceptEdits"


def _quote(path: Path) -> str:
    return json.dumps(str(path))


def _sandbox_profile(
    workdir: Path,
    tempdir: Path,
    home: Path,
    *,
    read_isolation: bool = False,
) -> str:
    workdir = workdir.resolve()
    allowed = [
        f"(subpath {_quote(workdir)})",
        f"(subpath {_quote(tempdir.resolve())})",
        f"(subpath {_quote((home / '.claude').resolve())})",
        f"(subpath {_quote((home / '.config').resolve())})",
        f"(subpath {_quote((home / 'Library' / 'Caches').resolve())})",
        f"(subpath {_quote((home / 'Library' / 'Application Support').resolve())})",
        f"(subpath {_quote((home / 'Library' / 'Logs').resolve())})",
        f"(literal {_quote((home / '.claude.json').resolve())})",
        # Claude Code 自身的会话/临时目录（不是项目代码）
        f"(subpath {_quote(Path('/private/tmp/claude-501').resolve())})",
        f"(subpath {_quote(Path('/private/tmp/claude').resolve())})",
        '(literal "/dev/null")',
    ]

    # 可选的读隔离：默认关闭，避免 Claude 因无法读取父目录而失败；
    # 需要严格隔离时用 TEAMCODE_SANDBOX_READ_ISOLATION=1 开启。
    read_rules = ""
    parts = workdir.parts
    index = parts.index(".teamcode") if ".teamcode" in parts else -1
    if (
        read_isolation
        and index >= 0
        and index + 1 < len(parts)
        and parts[index + 1] == "worktrees"
    ):
        worktrees_root = Path(*parts[: index + 2]).resolve()
        read_rules = (
            f"(deny file-read* (subpath {_quote(worktrees_root)}))"
            f"(allow file-read* (subpath {_quote(workdir)}))"
        )

    return (
        "(version 1)(allow default)(deny file-write*)"
        "(allow file-write* " + " ".join(allowed) + ")"
        # Claude Code 的 Bash 工具会写 /tmp/claude-<id>-cwd，放行这一类壳层文件
        '(allow file-write* (regex #"^/private/tmp/claude-[^/]+$"))'
        + read_rules
    )


def _tool_detail(name: str, payload: dict) -> str:
    for key in ("file_path", "path", "command", "pattern", "query", "url"):
        value = payload.get(key)
        if value:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return f"{name} {text[:240]}"
    return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Code streaming wrapper")
    parser.add_argument(
        "--continue-session",
        action="store_true",
        help="继续当前目录最近的 Claude 会话",
    )
    parser.add_argument(
        "--allowed-tools",
        default=os.getenv("TEAMCODE_CLAUDE_ALLOWED_TOOLS", DEFAULT_ALLOWED_TOOLS),
    )
    parser.add_argument(
        "--permission-mode",
        default=os.getenv("TEAMCODE_CLAUDE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE),
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(os.getenv("TEAMCODE_CLAUDE_HEARTBEAT", "10")),
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="关闭 macOS sandbox-exec 写隔离（默认开启）",
    )
    parser.add_argument(
        "--read-isolation",
        action="store_true",
        help="禁止读取其他任务 Worktree（默认关闭，开启后 Agent 可能无法 ls 父目录）",
    )
    args = parser.parse_args(argv)

    prompt = sys.stdin.read()
    if not prompt.strip():
        print("[wrapper] empty prompt", file=sys.stderr, flush=True)
        return 2

    command = [
        "claude",
        "-p",
        "--permission-mode",
        args.permission_mode,
        "--permission-prompts",
        "none",
        "--allowedTools",
        args.allowed_tools,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if args.continue_session:
        command.append("--continue")

    env = os.environ.copy()
    # 让 Agent 的 pytest/python 优先使用平台 venv
    env["PATH"] = (
        f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    )
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PYTEST_ADDOPTS", "-p no:cacheprovider")
    sandbox_temp: Path | None = None
    if not args.no_sandbox and os.getenv("TEAMCODE_SANDBOX", "1") != "0":
        sandbox_exec = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
        if os.path.exists(sandbox_exec):
            sandbox_temp = Path(
                tempfile.mkdtemp(prefix="teamcode-agent-", dir="/private/tmp")
            ).resolve()
            env["TMPDIR"] = str(sandbox_temp)
            profile = _sandbox_profile(
                Path.cwd(),
                sandbox_temp,
                Path.home().resolve(),
                read_isolation=(
                    args.read_isolation
                    or os.getenv(
                        "TEAMCODE_SANDBOX_READ_ISOLATION", "0"
                    )
                    == "1"
                ),
            )
            command = [sandbox_exec, "-p", profile, *command]
            print("[sandbox] 写操作限制在 Worktree 与专用临时目录", flush=True)
        else:
            print(
                "[sandbox] sandbox-exec 不可用，写隔离已关闭",
                file=sys.stderr,
                flush=True,
            )

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        print(f"[wrapper] 无法启动 claude: {exc}", file=sys.stderr, flush=True)
        if sandbox_temp is not None:
            shutil.rmtree(sandbox_temp, ignore_errors=True)
        return 1

    def _forward_signal(signum, _frame) -> None:
        """把终止信号转发给 claude 子进程，避免子进程成为孤儿。"""
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        finally:
            if sandbox_temp is not None:
                shutil.rmtree(sandbox_temp, ignore_errors=True)
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    def forward_stderr() -> None:
        for line in process.stderr:
            line = line.rstrip()
            if line:
                print(f"[stderr] {line}", file=sys.stderr, flush=True)

    stderr_thread = threading.Thread(target=forward_stderr, daemon=True)
    stderr_thread.start()

    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    failed = False
    last_action = "启动"
    last_output_at = time.monotonic()

    def emit(line: str) -> None:
        nonlocal last_output_at
        print(line, flush=True)
        last_output_at = time.monotonic()

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            emit(line[:2000])
            continue

        event_type = event.get("type")
        if event_type == "system":
            subtype = event.get("subtype")
            if subtype == "init":
                emit(
                    "[session] {} model={}".format(
                        event.get("session_id"), event.get("model", "?")
                    )
                )
            elif (
                subtype == "thinking_tokens"
                and time.monotonic() - last_output_at >= args.heartbeat_seconds
            ):
                # 只在长时间没有输出时给一条状态，避免刷屏
                emit(f"[status] 正在思考（上一步：{last_action}）")
        elif event_type == "assistant":
            for block in event.get("message", {}).get("content", []):
                block_type = block.get("type")
                if block_type == "text" and block.get("text"):
                    last_action = "输出说明"
                    emit(block["text"])
                elif block_type == "tool_use":
                    last_action = _tool_detail(
                        str(block.get("name", "tool")),
                        block.get("input", {}) or {},
                    )
                    emit(f"[tool] {last_action}")
        elif event_type == "user":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") != "tool_result":
                    continue
                content = block.get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else json.dumps(content, ensure_ascii=False)
                )
                emit(f"[tool-result] {text[:300]}")
        elif event_type == "result":
            subtype = str(event.get("subtype", ""))
            result = str(event.get("result", ""))
            emit(f"[result] {subtype} {result[:1000]}")
            if subtype and subtype != "success":
                failed = True

    exit_code = process.wait()
    stderr_thread.join(timeout=2)
    if sandbox_temp is not None:
        shutil.rmtree(sandbox_temp, ignore_errors=True)
    if exit_code != 0:
        return exit_code
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
