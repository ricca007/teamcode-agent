import re

from app.manager_agent.requirements import MODULE_LABELS, ordered_modules
from app.schemas.core import ParamInfo
from app.schemas.planning import (
    InterfaceContractDraft,
    PlannedTask,
    TeamMemberSpec,
)

TASK_PATH_PREFIXES = {
    "user": "backend/app/modules/user",
    "product": "backend/app/modules/product",
    "coupon": "backend/app/modules/coupon",
    "order": "backend/app/modules/order",
    "interface": "backend/app/interface_registry",
    "agent": "backend/app/manager_agent",
    "frontend": "frontend/src",
    "core": "backend/app",
}

DEPENDENCY_RULES = {
    "order": ("user", "product", "coupon"),
    "frontend": ("user", "product", "coupon", "order", "interface"),
    "agent": ("interface",),
}


def decompose_tasks(
    project_id: str,
    grouped: dict[str, list[str]],
    max_tasks: int,
) -> list[PlannedTask]:
    tasks: list[PlannedTask] = []
    for module in ordered_modules(grouped)[:max_tasks]:
        label = MODULE_LABELS.get(module, module.title())
        slug = _slug(module)
        allowed_path = TASK_PATH_PREFIXES.get(module, f"backend/app/modules/{slug}")
        tasks.append(
            PlannedTask(
                task_id=f"task_{slug}",
                project_id=project_id,
                module=module,
                title=f"Implement the {label.lower()} module",
                description=" ".join(grouped[module]),
                owner_id="",
                allowed_paths=[f"{allowed_path.rstrip('/')}/"],
                interface_requirements=[],
                acceptance_criteria=[
                    f"{label} behavior is covered by automated tests.",
                    f"{label} exposes the approved interface contract.",
                ],
                priority=0,
            )
        )
    return tasks


def infer_dependencies(tasks: list[PlannedTask]) -> list[PlannedTask]:
    by_module = {task.module: task for task in tasks}
    updated: list[PlannedTask] = []
    for task in tasks:
        dependencies = [
            by_module[module].task_id
            for module in DEPENDENCY_RULES.get(task.module, ())
            if module in by_module
        ]
        updated.append(
            task.model_copy(
                update={
                    "depends_on": dependencies,
                    "priority": len(dependencies) + 1,
                }
            )
        )
    return updated


def generate_interface_contracts(
    tasks: list[PlannedTask],
) -> tuple[list[PlannedTask], list[InterfaceContractDraft]]:
    task_to_contract = {task.task_id: f"iface_{_slug(task.module)}" for task in tasks}
    contracts: list[InterfaceContractDraft] = []
    updated_tasks: list[PlannedTask] = []

    for task in tasks:
        contract_name = f"{_pascal(task.module)}Service"
        dependencies = [
            task_to_contract[dependency]
            for dependency in task.depends_on
            if dependency in task_to_contract
        ]
        contract = InterfaceContractDraft(
            interface_id=task_to_contract[task.task_id],
            module=task.module,
            file_path=f"{task.allowed_paths[0].rstrip('/')}/{_slug(task.module)}_service.py",
            name=contract_name,
            kind="class",
            params=[ParamInfo(name="session", annotation="AsyncSession")],
            returns=None,
            docstring=f"Public contract for the {task.module} module.",
            dependencies=dependencies,
        )
        contracts.append(contract)
        updated_tasks.append(task.model_copy(update={"interface_requirements": [contract_name]}))

    return updated_tasks, contracts


def assign_tasks(
    tasks: list[PlannedTask],
    members: list[TeamMemberSpec],
) -> list[PlannedTask]:
    loads = {member.member_id: 0 for member in members}
    assigned: list[PlannedTask] = []

    for task in tasks:
        matching = [
            member
            for member in members
            if any(_area_matches(area, task.module) for area in member.areas)
        ]
        candidates = matching or members
        owner = min(candidates, key=lambda member: (loads[member.member_id], member.member_id))
        loads[owner.member_id] += 1
        assigned.append(task.model_copy(update={"owner_id": owner.member_id}))

    return assigned


def _area_matches(area: str, module: str) -> bool:
    normalized = area.strip().lower()
    return normalized == module or normalized.startswith(f"{module},") or f",{module}" in normalized


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "module"


def _pascal(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", value) if part)
