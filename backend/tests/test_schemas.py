from app.schemas import AgentStatus, TaskSpec


def test_task_spec_defaults_to_no_dependencies() -> None:
    task = TaskSpec(
        task_id="task-1",
        title="Build a module",
        description="Implement the module contract.",
        owner_id="member-a",
        allowed_paths=["backend/app/example"],
        interface_requirements=["ExampleService.run"],
        acceptance_criteria=["Tests pass"],
    )

    assert task.depends_on == []
    assert task.priority == 0


def test_agent_status_serializes_to_string_value() -> None:
    assert AgentStatus.RUNNING.value == "running"
