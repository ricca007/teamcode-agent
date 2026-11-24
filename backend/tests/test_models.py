from sqlalchemy.ext.asyncio import create_async_engine

from app.models import AgentSession, Base, InterfaceContract, Task

EXPECTED_TABLES = {
    "agent_logs",
    "agent_sessions",
    "api_keys",
    "auth_sessions",
    "code_changes",
    "interface_contracts",
    "interface_registry_state",
    "interface_versions",
    "join_requests",
    "plan_snapshots",
    "project_members",
    "projects",
    "task_dependencies",
    "tasks",
    "user_credentials",
    "users",
}


async def test_models_create_all_tables() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    assert set(Base.metadata.tables) == EXPECTED_TABLES
    await engine.dispose()


def test_task_dependencies_use_composite_primary_key() -> None:
    table = Base.metadata.tables["task_dependencies"]

    assert {column.name for column in table.primary_key.columns} == {
        "task_id",
        "depends_on_task_id",
    }


def test_project_members_use_composite_primary_key() -> None:
    table = Base.metadata.tables["project_members"]

    assert {column.name for column in table.primary_key.columns} == {
        "project_id",
        "user_id",
    }


def test_enum_columns_store_lowercase_contract_values() -> None:
    task_status = Base.metadata.tables["tasks"].c.status.type
    session_status = Base.metadata.tables["agent_sessions"].c.status.type

    assert task_status.enums == ["planned", "in_progress", "blocked", "completed", "cancelled"]
    assert session_status.enums == [
        "pending",
        "running",
        "paused",
        "succeeded",
        "failed",
        "terminated",
    ]


def test_models_expose_schema_compatible_aliases() -> None:
    task = Task(id="task_1")
    task.dependencies = []
    session = AgentSession(id="session_1")
    interface = InterfaceContract(id="interface_1")

    assert task.task_id == "task_1"
    assert task.depends_on == []
    assert session.session_id == "session_1"
    assert interface.interface_id == "interface_1"


def test_agent_log_tracks_sequence() -> None:
    table = Base.metadata.tables["agent_logs"]

    assert table.c.sequence.nullable is False
    assert table.c.sequence.server_default is not None
    assert "ix_agent_logs_session_id_sequence" in {index.name for index in table.indexes}
