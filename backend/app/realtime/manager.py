"""WebSocket 连接管理与事件总线。

解耦要点：
- ``ConnectionManager`` 只管连接集合，不关心事件从哪来；
- ``EventBus`` 是发布入口，支持：
  1. 同步订阅者（测试、日志、后续接 Redis/Kafka 都可以挂在这里）；
  2. FastAPI 的 WebSocket 广播（绑定事件循环后跨线程安全）；
- 业务代码（watcher / API）只调用 ``bus.publish(event)``，与 Web 框架无关。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """按 project_id 分组维护 WebSocket 连接。

    每个连接可以携带 ``allowed_task_ids``（成员身份）：广播时过滤掉
    不属于该成员的任务事件，避免成员看到别人的 Agent 日志/变更。
    ``None`` 表示队长或未启用鉴权，允许全部任务。
    """

    def __init__(self) -> None:
        self._connections: dict[str, dict[WebSocket, set[str] | None]] = defaultdict(
            dict
        )
        self._lock = asyncio.Lock()

    async def connect(
        self,
        project_id: str,
        websocket: WebSocket,
        allowed_task_ids: set[str] | None = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[project_id][websocket] = allowed_task_ids

    async def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(project_id)
            if connections is None:
                return
            connections.pop(websocket, None)
            if not connections:
                self._connections.pop(project_id, None)

    async def broadcast(self, project_id: str, event: dict[str, Any]) -> None:
        with_task = event.get("task_id")
        async with self._lock:
            targets = list(self._connections.get(project_id, {}).items())

        dead: list[WebSocket] = []
        event_type = event.get("type")
        for websocket, allowed_tasks in targets:
            if (
                allowed_tasks is not None
                and with_task
                and event_type in {"agent.log", "code.changed"}
                and str(with_task) not in allowed_tasks
            ):
                # 成员只接收自己任务的日志/变更；task.updated 需要广播，
                # 否则新分配的任务无法实时出现在成员看板上
                continue
            try:
                await websocket.send_json(event)
            except Exception:
                logger.warning(
                    "WebSocket 推送失败，移除连接: project=%s event=%s",
                    project_id,
                    event.get("type"),
                    exc_info=True,
                )
                dead.append(websocket)

        for websocket in dead:
            await self.disconnect(project_id, websocket)

    def count(self, project_id: str) -> int:
        return len(self._connections.get(project_id, {}))


class EventBus:
    """事件发布总线。"""

    def __init__(self) -> None:
        self._manager: ConnectionManager | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sinks: list[Callable[[dict[str, Any]], None]] = []

    def attach_manager(self, manager: ConnectionManager) -> None:
        self._manager = manager

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """由 WebSocket 路由在连接建立时绑定，避免修改 A 的应用入口。"""
        self._loop = loop

    def unbind_loop(self) -> None:
        self._loop = None

    def add_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        """注册同步订阅者；测试或未来接入外部消息队列时使用。"""
        self._sinks.append(sink)

    def remove_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    def publish(self, event: dict[str, Any]) -> None:
        # 1) 同步订阅者：任何线程都可以安全调用
        for sink in list(self._sinks):
            try:
                sink(event)
            except Exception:  # pragma: no cover - 订阅者异常不影响主流程
                logger.exception("事件订阅者处理失败")

        # 2) WebSocket 广播：需要绑定事件循环
        manager = self._manager
        loop = self._loop
        if manager is None or loop is None or not loop.is_running():
            logger.debug("没有可用的 WebSocket 事件循环，仅通知同步订阅者: %s", event.get("type"))
            return
        try:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(event["project_id"], event), loop
            )
        except RuntimeError:  # pragma: no cover - 事件循环已关闭
            logger.warning("事件循环不可用，丢弃事件: %s", event.get("type"))
        except Exception:  # pragma: no cover - 广播调度异常不应影响业务
            logger.exception("调度 WebSocket 广播失败，丢弃事件: %s", event.get("type"))


manager = ConnectionManager()
bus = EventBus()
bus.attach_manager(manager)
