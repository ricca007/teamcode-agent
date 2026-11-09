"""文件 sha256 缓存，用于增量扫描。

只做一件事：记录「相对路径 -> 文件内容哈希」，与具体存储引擎解耦。
默认落盘为项目根目录下的 ``.teamcode/interface_cache.json``；
测试也可以只构造内存实例（path=None）。
"""

from __future__ import annotations

import json
from pathlib import Path


class HashCache:
    def __init__(self, data: dict[str, str] | None = None, path: str | Path | None = None):
        self._data: dict[str, str] = dict(data or {})
        self._path = Path(path) if path is not None else None

    # ---------- 读写 ----------
    @classmethod
    def load(cls, path: str | Path) -> HashCache:
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("缓存格式错误")
            return cls({str(k): str(v) for k, v in data.items()}, path=p)
        except (OSError, ValueError, json.JSONDecodeError):
            # 缓存损坏时退化为全量扫描，不影响正确性
            return cls(path=p)

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # ---------- 字典语义 ----------
    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def remove(self, key: str) -> None:
        self._data.pop(key, None)

    def keys(self) -> list[str]:
        return sorted(self._data)

    def is_empty(self) -> bool:
        return not self._data

    def __len__(self) -> int:
        return len(self._data)
