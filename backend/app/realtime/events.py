"""WebSocket 事件构造。

事件格式见 docs/interface_contract.md，三种角色共用：
``task.updated``（A）、``agent.log`` / ``code.changed``（B）、
``interface.updated``（C）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

EventType = Literal["task.updated", "agent.log", "interface.updated", "code.changed"]


def make_event(
    event_type: EventType,
    project_id: str,
    payload: dict[str, Any] | None = None,
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "project_id": project_id,
        "task_id": task_id,
        "payload": payload or {},
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
