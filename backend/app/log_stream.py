"""Small in-process event broker used by the Agent Runtime.

The production implementation can replace this with the project WebSocket
hub while preserving ``publish`` and ``subscribe`` semantics.
"""

from __future__ import annotations

import asyncio
import copy
from collections import defaultdict
from typing import Any


class LogBroker:
    def __init__(self, max_history: int = 10000) -> None:
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        self.max_history = max_history
        self._subscribers: defaultdict[str, set[asyncio.Queue]] = defaultdict(set)
        self._events: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        self._event_ids: defaultdict[str, int] = defaultdict(int)
        self._closed = False

    def subscribe(self, project_id: str, after_event_id: int = 0) -> asyncio.Queue:
        if self._closed:
            raise RuntimeError("LogBroker is closed")
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[project_id].add(queue)
        for event in self.history(project_id, after_event_id):
            queue.put_nowait(event)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[project_id].discard(queue)
        if not self._subscribers[project_id]:
            self._subscribers.pop(project_id, None)

    def history(self, project_id: str, after_event_id: int = 0) -> list[dict[str, Any]]:
        """Return buffered events for reconnecting WebSocket clients."""

        try:
            after = int(after_event_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("after_event_id must be an integer") from exc
        if self._closed:
            raise RuntimeError("LogBroker is closed")
        return [
            copy.deepcopy(event)
            for event in self._events.get(project_id, ())
            if int(event.get("event_id", 0)) > after
        ]

    def close(self) -> None:
        """Drop subscribers and in-memory history during shutdown."""

        self._closed = True
        self._subscribers.clear()
        self._events.clear()

    async def publish(self, project_id: str, event: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("LogBroker is closed")
        self._event_ids[project_id] += 1
        enriched = copy.deepcopy(event)
        enriched["event_id"] = self._event_ids[project_id]
        self._events[project_id].append(enriched)
        if len(self._events[project_id]) > self.max_history:
            self._events[project_id] = self._events[project_id][-self.max_history:]
        for queue in list(self._subscribers.get(project_id, ())):
            await queue.put(copy.deepcopy(enriched))
