"""接口 ID 生成工具。

采用「身份字段 + 稳定哈希」而不是自增主键，好处：
- 同一接口在多次扫描后 ID 不变，前端和外部 Agent 可以缓存；
- 接口被删除后重新出现时仍能复用 ID；
- 与数据库无关，便于未来迁移到其他存储。
"""

from __future__ import annotations

import hashlib


def make_interface_id(project_id: str, file_path: str, name: str, kind: str) -> str:
    raw = f"{project_id}|{file_path}|{name}|{kind}".encode()
    return "iface_" + hashlib.sha256(raw).hexdigest()[:16]
