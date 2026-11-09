from app.manager_agent.workflow import create_plan
from app.schemas.planning import (
    InterfaceContractChange,
    PlanDiff,
    PlannedTask,
    PlanningRequest,
    PlanResult,
    ReplanResult,
    TaskDependencyChange,
    TaskFieldChange,
)

TASK_COMPARISON_FIELDS = (
    "module",
    "title",
    "description",
    "owner_id",
    "allowed_paths",
    "interface_requirements",
    "acceptance_criteria",
    "priority",
)


def replan(previous_plan: PlanResult, request: PlanningRequest) -> ReplanResult:
    generated = create_plan(request)
    previous_tasks = {task.task_id: task for task in previous_plan.tasks}
    available_members = {member.member_id for member in request.members}
    tasks = [
        _preserve_owner(task, previous_tasks.get(task.task_id), available_members)
        for task in generated.tasks
    ]
    plan = generated.model_copy(
        update={
            "version": previous_plan.version + 1,
            "tasks": tasks,
        }
    )
    return ReplanResult(
        previous_version=previous_plan.version,
        plan=plan,
        diff=diff_plans(previous_plan, plan),
    )


def diff_plans(previous: PlanResult, current: PlanResult) -> PlanDiff:
    previous_tasks = {task.task_id: task for task in previous.tasks}
    current_tasks = {task.task_id: task for task in current.tasks}
    previous_ids = set(previous_tasks)
    current_ids = set(current_tasks)

    updated_tasks = [
        TaskFieldChange(task_id=task_id, changed_fields=changed_fields)
        for task_id in sorted(previous_ids & current_ids)
        if (changed_fields := _changed_fields(previous_tasks[task_id], current_tasks[task_id]))
    ]
    unchanged_tasks = sorted(
        task_id
        for task_id in previous_ids & current_ids
        if not _changed_fields(previous_tasks[task_id], current_tasks[task_id])
        and previous_tasks[task_id].depends_on == current_tasks[task_id].depends_on
    )

    dependency_changes = [
        TaskDependencyChange(
            task_id=task_id,
            before=previous_tasks[task_id].depends_on if task_id in previous_tasks else [],
            after=current_tasks[task_id].depends_on if task_id in current_tasks else [],
        )
        for task_id in sorted(previous_ids | current_ids)
        if _dependencies(previous_tasks.get(task_id)) != _dependencies(current_tasks.get(task_id))
    ]

    interface_changes = _interface_changes(previous, current)
    added_tasks = sorted(current_ids - previous_ids)
    removed_tasks = sorted(previous_ids - current_ids)
    impact_notes = _impact_notes(
        added_tasks,
        removed_tasks,
        updated_tasks,
        dependency_changes,
        interface_changes,
    )

    return PlanDiff(
        added_tasks=added_tasks,
        removed_tasks=removed_tasks,
        updated_tasks=updated_tasks,
        unchanged_tasks=unchanged_tasks,
        dependency_changes=dependency_changes,
        interface_changes=interface_changes,
        impact_notes=impact_notes,
    )


def _preserve_owner(
    task: PlannedTask,
    previous: PlannedTask | None,
    available_members: set[str],
) -> PlannedTask:
    if previous is None or previous.owner_id not in available_members:
        return task
    return task.model_copy(update={"owner_id": previous.owner_id})


def _changed_fields(before: PlannedTask, after: PlannedTask) -> list[str]:
    return [
        field for field in TASK_COMPARISON_FIELDS if getattr(before, field) != getattr(after, field)
    ]


def _dependencies(task: PlannedTask | None) -> list[str]:
    return task.depends_on if task is not None else []


def _interface_changes(
    previous: PlanResult,
    current: PlanResult,
) -> list[InterfaceContractChange]:
    previous_contracts = {
        contract.interface_id: contract for contract in previous.interface_contracts
    }
    current_contracts = {
        contract.interface_id: contract for contract in current.interface_contracts
    }
    changes: list[InterfaceContractChange] = []

    for interface_id in sorted(previous_contracts.keys() | current_contracts.keys()):
        before = previous_contracts.get(interface_id)
        after = current_contracts.get(interface_id)
        if before is None:
            changes.append(
                InterfaceContractChange(
                    interface_id=interface_id,
                    change_type="added",
                    after=after,
                )
            )
        elif after is None:
            changes.append(
                InterfaceContractChange(
                    interface_id=interface_id,
                    change_type="removed",
                    before=before,
                )
            )
        elif before != after:
            changes.append(
                InterfaceContractChange(
                    interface_id=interface_id,
                    change_type="updated",
                    before=before,
                    after=after,
                )
            )

    return changes


def _impact_notes(
    added_tasks: list[str],
    removed_tasks: list[str],
    updated_tasks: list[TaskFieldChange],
    dependency_changes: list[TaskDependencyChange],
    interface_changes: list[InterfaceContractChange],
) -> list[str]:
    notes: list[str] = []
    if added_tasks:
        notes.append(f"Added tasks: {', '.join(added_tasks)}")
    if removed_tasks:
        notes.append(f"Removed tasks: {', '.join(removed_tasks)}")
    if updated_tasks:
        notes.append(f"Updated tasks: {', '.join(change.task_id for change in updated_tasks)}")
    affected_dependencies = {change.task_id for change in dependency_changes}
    if affected_dependencies:
        notes.append(f"Dependencies changed for: {', '.join(sorted(affected_dependencies))}")
    affected_interfaces = {change.interface_id for change in interface_changes}
    if affected_interfaces:
        notes.append(f"Interfaces changed for: {', '.join(sorted(affected_interfaces))}")
    if not notes:
        notes.append("No task, dependency, or interface changes detected.")
    return notes
