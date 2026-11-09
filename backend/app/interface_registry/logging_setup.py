"""C 模块统一日志配置。

原则：
- 服务进程若 root logger 还没有 handler，补一个 stderr handler；
- 无论是否已有 handler，都把 C 的 logger 级别设为 INFO，避免被默认
  WARNING 级别吞掉；
- 幂等：重复调用不会重复添加 handler；
- 测试环境 pytest 已配置 logging 时不覆盖，只调整 C 的 logger 级别。
"""

from __future__ import annotations

import logging
import sys

C_LOGGER_NAMES = ("app.interface_registry", "app.realtime")


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(level)

    for name in C_LOGGER_NAMES:
        logging.getLogger(name).setLevel(level)
