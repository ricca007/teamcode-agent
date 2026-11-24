"""C-2 验收测试：WebSocket 连接管理与事件总线。"""

from __future__ import annotations

import asyncio

from app.realtime.events import make_event
from app.realtime.manager import ConnectionManager, EventBus


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, event: dict) -> None:
        self.sent.append(event)


def test_connection_manager_broadcast_and_disconnect():
    manager = ConnectionManager()
    websocket = FakeWebSocket()

    asyncio.run(manager.connect("p_001", websocket))
    assert websocket.accepted is True
    assert manager.count("p_001") == 1

    asyncio.run(manager.broadcast("p_001", {"type": "interface.updated"}))
    assert websocket.sent == [{"type": "interface.updated"}]

    asyncio.run(manager.disconnect("p_001", websocket))
    assert manager.count("p_001") == 0


def test_connection_manager_isolated_by_project():
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()

    asyncio.run(manager.connect("p_001", first))
    asyncio.run(manager.connect("p_002", second))

    asyncio.run(manager.broadcast("p_001", {"type": "interface.updated"}))
    assert len(first.sent) == 1
    assert second.sent == []


def test_event_bus_sync_sink():
    bus = EventBus()
    received: list[dict] = []
    bus.add_sink(received.append)

    bus.publish(make_event("interface.updated", "p_001", {"added": ["i1"]}))

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "interface.updated"
    assert event["project_id"] == "p_001"
    assert event["task_id"] is None
    assert event["payload"] == {"added": ["i1"]}
    assert event["ts"].endswith("Z")


def test_event_bus_without_loop_does_not_raise():
    bus = EventBus()
    bus.publish(make_event("interface.updated", "p_001"))


def test_dead_connection_is_dropped():
    class BrokenWebSocket(FakeWebSocket):
        async def send_json(self, event: dict) -> None:
            raise RuntimeError("连接已断开")

    manager = ConnectionManager()
    broken = BrokenWebSocket()
    asyncio.run(manager.connect("p_001", broken))
    asyncio.run(manager.broadcast("p_001", {"type": "interface.updated"}))
    assert manager.count("p_001") == 0


async def test_reassignment_updates_live_member_log_permissions():
    manager = ConnectionManager()
    old_owner = FakeWebSocket()
    new_owner = FakeWebSocket()
    await manager.connect("p_001", old_owner, {"t1"}, user_id="old")
    await manager.connect("p_001", new_owner, set(), user_id="new")
    await manager.broadcast("p_001", make_event(
        "task.updated", "p_001", {"task_id": "t1", "owner_id": "new"}, task_id="t1"
    ))
    event = make_event("agent.log", "p_001", {"message": "private"}, task_id="t1")
    await manager.broadcast("p_001", event)
    assert not any(item["type"] == "agent.log" for item in old_owner.sent)
    assert new_owner.sent[-1] == event
