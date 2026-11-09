from pathlib import Path

from app.manager_agent import create_plan, replan
from app.schemas import PlanningRequest, TeamMemberSpec


def _request(repo_path: Path, requirements: str) -> PlanningRequest:
    return PlanningRequest(
        project_id="project_shop",
        requirements=requirements,
        repo_path=str(repo_path),
        members=[
            TeamMemberSpec(member_id="member_a", name="A", areas=["user"]),
            TeamMemberSpec(member_id="member_b", name="B", areas=["order"]),
            TeamMemberSpec(member_id="member_c", name="C", areas=["product"]),
        ],
    )


def _base_requirements() -> str:
    return (
        "Build an online store.\n"
        "- Users can register and log in.\n"
        "- Products can be searched and managed.\n"
        "- Orders can be created and paid."
    )


def test_identical_replan_has_no_changes_and_increments_version(tmp_path: Path) -> None:
    request = _request(tmp_path, _base_requirements())
    previous = create_plan(request)

    result = replan(previous, request)

    assert result.plan.version == previous.version + 1
    assert result.diff.has_changes is False
    assert result.diff.unchanged_tasks == sorted(task.task_id for task in previous.tasks)
    assert [task.owner_id for task in result.plan.tasks] == [
        task.owner_id for task in previous.tasks
    ]


def test_replan_adds_frontend_task_and_dependencies(tmp_path: Path) -> None:
    request = _request(tmp_path, _base_requirements())
    previous = create_plan(request)
    updated_request = request.model_copy(
        update={"requirements": f"{request.requirements}\n- Add a React dashboard."}
    )

    result = replan(previous, updated_request)

    assert result.diff.added_tasks == ["task_frontend"]
    frontend = next(task for task in result.plan.tasks if task.task_id == "task_frontend")
    assert set(frontend.depends_on) == {"task_user", "task_product", "task_order"}
    assert any(change.task_id == "task_frontend" for change in result.diff.dependency_changes)
    assert any(change.interface_id == "iface_frontend" for change in result.diff.interface_changes)


def test_replan_removes_order_task_and_contract(tmp_path: Path) -> None:
    request = _request(tmp_path, _base_requirements())
    previous = create_plan(request)
    updated_request = request.model_copy(
        update={
            "requirements": (
                "Build an online store.\n"
                "- Users can register and log in.\n"
                "- Products can be searched and managed."
            )
        }
    )

    result = replan(previous, updated_request)

    assert result.diff.removed_tasks == ["task_order"]
    assert "task_order" not in {task.task_id for task in result.plan.tasks}
    assert {change.interface_id for change in result.diff.interface_changes} == {"iface_order"}
    assert result.diff.interface_changes[0].change_type == "removed"


def test_replan_marks_only_changed_task_and_preserves_owner(tmp_path: Path) -> None:
    request = _request(tmp_path, _base_requirements())
    previous = create_plan(request)
    previous_user_owner = next(
        task.owner_id for task in previous.tasks if task.task_id == "task_user"
    )
    updated_request = request.model_copy(
        update={
            "requirements": request.requirements.replace(
                "Users can register and log in.",
                "Users can register, log in, and verify email addresses.",
            )
        }
    )

    result = replan(previous, updated_request)

    assert [change.task_id for change in result.diff.updated_tasks] == ["task_user"]
    assert result.diff.updated_tasks[0].changed_fields == ["description"]
    user_task = next(task for task in result.plan.tasks if task.task_id == "task_user")
    assert user_task.owner_id == previous_user_owner


def test_replan_preserves_owner_when_assignment_would_otherwise_change(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, _base_requirements())
    previous = create_plan(request)
    previous_user_owner = next(
        task.owner_id for task in previous.tasks if task.task_id == "task_user"
    )
    updated_request = request.model_copy(
        update={
            "members": [
                TeamMemberSpec(member_id="aaa", name="New A", areas=["user"]),
                *request.members,
            ]
        }
    )

    result = replan(previous, updated_request)

    user_task = next(task for task in result.plan.tasks if task.task_id == "task_user")
    assert user_task.owner_id == previous_user_owner
