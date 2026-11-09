#!/usr/bin/env python3
"""通用 CLI Agent 包装器。

B 的 CLIAdapter 以 stdin 模式把 prompt 交给本脚本；本脚本再按指定方式
把 prompt 传给真正的 CLI Agent：

- stdin: 直接把 prompt 写入子进程 stdin；
- arg:   把 prompt 作为一个参数追加到命令末尾；
- file:  把 prompt 写入临时文件，并把文件路径追加到命令末尾。

子进程的 stdout/stderr 直接继承，因此 B 的日志流仍能实时看到输出。
用法（由集成层拼接）：
    python agent_cli_wrapper.py --prompt-mode arg -- codex exec
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generic CLI Agent wrapper")
    parser.add_argument(
        "--prompt-mode", choices=["stdin", "arg", "file"], default="stdin"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("[agent-wrapper] 未配置 Agent 命令", file=sys.stderr, flush=True)
        return 2

    binary = command[0]
    if not (shutil.which(binary) or Path(binary).exists()):
        print(
            f"[agent-wrapper] 找不到 Agent 命令: {binary}",
            file=sys.stderr,
            flush=True,
        )
        return 127

    prompt = sys.stdin.read()

    prompt_file: Path | None = None
    final_command = list(command)
    stdin: int = subprocess.DEVNULL
    if args.prompt_mode == "stdin":
        stdin = subprocess.PIPE
    elif args.prompt_mode == "arg":
        final_command.append(prompt)
    else:
        fd, raw_path = tempfile.mkstemp(
            prefix="teamcode-prompt-", suffix=".txt", text=True
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(prompt)
        prompt_file = Path(raw_path)
        final_command.append(str(prompt_file))

    try:
        process = subprocess.Popen(
            final_command,
            cwd=os.getcwd(),
            stdin=stdin,
            stdout=None,
            stderr=None,
            env=os.environ.copy(),
        )
    except OSError as exc:
        print(f"[agent-wrapper] 启动失败: {exc}", file=sys.stderr, flush=True)
        if prompt_file is not None:
            prompt_file.unlink(missing_ok=True)
        return 1

    def forward(signum, _frame) -> None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        finally:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    if args.prompt_mode == "stdin" and process.stdin is not None:
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()

    try:
        code = process.wait()
    finally:
        if prompt_file is not None:
            prompt_file.unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
