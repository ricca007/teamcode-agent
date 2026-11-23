"""日志 sequence 与 id 规则的回归测试（P0-1）。

覆盖：
- 同一时间戳的 12 条日志按 sequence 正常排序（旧逻辑 9→10 会乱序）；
- id 统一为 ``log_{session_id}_{sequence:06d}``；
- ``task_logs`` 返回真实 sequence；
- WebSocket ``agent.log`` 事件带真实 sequence；
- 重复 flush 不重复插入。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.agent_runtime.session_manager import SessionManager
from app.integration.service import IntegrationService, ProjectRuntime
from app.models.project import Project
from app.models.runtime import AgentLog as AgentLogModel
from app.models.runtime import AgentSession as AgentSessionModel
from app.models.task import Task
from app.models.user import User
from app.realtime.manager import bus
from app.schemas.core import AgentLog

FIXED_TS = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
SESSION_ID = "session_seq"
TASK_ID = "task_seq"
PROJECT_ID = "project_seq"
LOG_COUNT = 12


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id="user_seq", name="Owner", email="owner@example.invalid"))
        db.add(
            Project(
                id=PROJECT_ID,
                name="序列项目",
                owner_id="user_seq",
                repo_path=".",
            )
        )
        db.add(
            Task(
                id=TASK_ID,
                project_id=PROJECT_ID,
                title="序列任务",
                description="测试日志排序",
                owner_id="user_seq",
            )
        )
        db.add(
            AgentSessionModel(
                id=SESSION_ID,
                task_id=TASK_ID,
                adapter="mock",
                workspace=".",
            )
        )
        await db.commit()


def _runtime_with_logs() -> ProjectRuntime:
    runtime = ProjectRuntime(project_id=PROJECT_ID, repo_root=Path("."))
    runtime.sessions = SessionManager()
    for index in range(LOG_COUNT):
        runtime.sessions.store.append_log(
            AgentLog(
                session_id=SESSION_ID,
                task_id=TASK_ID,
                ts=FIXED_TS,
                level="info",
                message=f"line-{index}",
                sequence=index,
            )
        )
    return runtime


async def test_flush_logs_assigns_monotonic_sequence_and_ids(session_factory):
    await _seed(session_factory)
    runtime = _runtime_with_logs()

    events: list[dict] = []
    sink = events.append
    bus.add_sink(sink)
    try:
        async with session_factory() as db:
            service = IntegrationService(db, session_factory)
            seen = await service._flush_logs(
                db, PROJECT_ID, TASK_ID, SESSION_ID, runtime, 0
            )
        assert seen == LOG_COUNT
    finally:
        bus.remove_sink(sink)

    async with session_factory() as db:
        rows = (
            await db.scalars(
                select(AgentLogModel)
                .where(AgentLogModel.session_id == SESSION_ID)
                .order_by(AgentLogModel.sequence)
            )
        ).all()

    assert [row.sequence for row in rows] == list(range(1, LOG_COUNT + 1))
    assert [row.id for row in rows] == [
        f"log_{SESSION_ID}_{index:06d}" for index in range(1, LOG_COUNT + 1)
    ]
    assert [row.message for row in rows] == [
        f"line-{index}" for index in range(LOG_COUNT)
    ]

    log_events = [event for event in events if event["type"] == "agent.log"]
    assert [event["payload"]["sequence"] for event in log_events] == list(
        range(1, LOG_COUNT + 1)
    )


async def test_task_logs_orders_by_sequence_and_reports_sequence(session_factory):
    await _seed(session_factory)
    runtime = _runtime_with_logs()
    async with session_factory() as db:
        service = IntegrationService(db, session_factory)
        await service._flush_logs(db, PROJECT_ID, TASK_ID, SESSION_ID, runtime, 0)

    async with session_factory() as db:
        service = IntegrationService(db, session_factory)
        logs = await service.task_logs(TASK_ID)

    assert [entry["message"] for entry in logs] == [
        f"line-{index}" for index in range(LOG_COUNT)
    ]
    assert [entry["sequence"] for entry in logs] == list(range(1, LOG_COUNT + 1))


async def test_repeated_flush_does_not_duplicate(session_factory):
    await _seed(session_factory)
    runtime = _runtime_with_logs()
    async with session_factory() as db:
        service = IntegrationService(db, session_factory)
        seen = await service._flush_logs(
            db, PROJECT_ID, TASK_ID, SESSION_ID, runtime, 0
        )
        seen = await service._flush_logs(
            db, PROJECT_ID, TASK_ID, SESSION_ID, runtime, seen
        )

    async with session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(AgentLogModel)
            .where(AgentLogModel.session_id == SESSION_ID)
        )

    assert seen == LOG_COUNT
    assert count == LOG_COUNT
