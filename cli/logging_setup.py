"""CLI 日志配置。

约定：
- 所有日志写 stderr；stdout 只留给命令结果或 MCP 协议消息；
- 每次 ``main()`` 都重新绑定当前 stderr，确保测试的 capsys 能捕获；
- 只保留一个 handler，避免重复输出。
"""

from __future__ import annotations

import logging
import sys


def configure_cli_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger("teamcode")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
