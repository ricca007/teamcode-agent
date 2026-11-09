"""C 模块自己的配置项。

只放在 C 负责的目录内，避免改动 A 维护的 ``app/config.py``。
"""

from __future__ import annotations

import os

DEFAULT_INTERFACE_CACHE_PATH = ".teamcode/interface_cache.json"


def interface_cache_path() -> str:
    """增量扫描缓存文件相对项目根目录的位置（位于被忽略的 .teamcode 下）。"""
    return os.getenv("INTERFACE_CACHE_PATH", DEFAULT_INTERFACE_CACHE_PATH)
