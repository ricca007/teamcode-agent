import argparse
import json
import time
from pathlib import Path
from typing import Any

from app.manager_agent import create_plan, replan
from app.schemas import PlanningRequest, PlanResult, TeamMemberSpec

ROOT = Path(__file__).resolve().parents[1]

FIXTURE_REPO = ROOT / "experiments" / "fixtures" / "online_store"
BASE_REQUIREMENTS = (
    "Build an online store.\n"
    "- Users can register and log in.\n"
    "- Products can be searched and managed.\n"
    "- Orders can be created and paid."
)
COUPON_REQUIREMENT = (
    "Add a coupon feature, and require the order module to support coupon deduction."
)
EXPECTED_MODULES = {"user", "product", "order"}
EXPECTED_DEPENDENCIES = {
    ("order", "user"),
    ("order", "product"),
}
EXPECTED_AFFECTED_TASKS = {"task_coupon", "task_order"}
EXPECTED_UNAFFECTED_TASKS = {"task_user", "task_product"}


def build_request(requirements: str = BASE_REQUIREMENTS) -> PlanningRequest:
    return PlanningRequest(
        project_id="eval_online_store",
        requirements=requirements,
        repo_path=str(FIXTURE_REPO),
        members=[
            TeamMemberSpec(member_id="member_a", name="A", areas=["user"]),
            TeamMemberSpec(member_id="member_b", name="B", areas=["order"]),
            TeamMemberSpec(member_id="member_c", name="C", areas=["product"]),
        ],
    )


def run_evaluation(fail_under: float = 0.9) -> dict[str, Any]:
    request = build_request()
    planning_started = time.perf_counter()
    baseline_plan = create_plan(request)
    planning_ms = _elapsed_ms(planning_started)

    updated_request = request.model_copy(
        update={"requirements": f"{request.requirements}\n- {COUPON_REQUIREMENT}"}
    )
    replanning_started = time.perf_counter()
    replan_result = replan(baseline_plan, updated_request)
    replanning_ms = _elapsed_ms(replanning_started)

    experiment_1 = _evaluate_baseline(baseline_plan, planning_ms)
    experiment_4 = _evaluate_replan(
        baseline_plan,
        replan_result.plan,
        replan_result.diff,
        replanning_ms,
    )
    overall_score = round(
        (
            experiment_1["metrics"]["overall_score"]
            + experiment_4["metrics"]["overall_score"]
        )
        / 2,
        4,
    )
    passed = (
        experiment_1["passed"]
        and experiment_4["passed"]
        and overall_score >= fail_under
    )

    return {
        "scenario": "online_store_coupon_change",
        "fixture_repo": FIXTURE_REPO.relative_to(ROOT).as_posix(),
        "threshold": fail_under,
        "overall_score": overall_score,
        "passed": passed,
        "experiment_1_planning": experiment_1,
        "experiment_4_replanning": experiment_4,
        "manual_review": {
            "task_decomposition_reasonable": None,
            "dependency_analysis_reasonable": None,
            "interface_contracts_complete": None,
            "affected_modules_reasonable": None,
            "unaffected_tasks_preserved": None,
        },
    }


def _evaluate_baseline(plan: PlanResult, elapsed_ms: float) -> dict[str, Any]:
    modules = {task.module for task in plan.tasks}
    task_recall = _ratio(len(modules & EXPECTED_MODULES), len(EXPECTED_MODULES))
    unexpected_rate = _ratio(len(modules - EXPECTED_MODULES), max(len(modules), 1))
    dependency_edges = _dependency_edges(plan)
    dependency_recall = _ratio(
        len(dependency_edges & EXPECTED_DEPENDENCIES),
        len(EXPECTED_DEPENDENCIES),
    )
    contract_modules = {contract.module for contract in plan.interface_contracts}
    contract_coverage = _ratio(len(modules & contract_modules), max(len(modules), 1))
    executable_rate = _ratio(
        sum(_task_is_executable(task) for task in plan.tasks),
        max(len(plan.tasks), 1),
    )
    assignment_coverage = _ratio(
        sum(bool(task.owner_id) for task in plan.tasks),
        max(len(plan.tasks), 1),
    )
    overall_score = round(
        (
            task_recall
            + (1 - unexpected_rate)
            + dependency_recall
            + contract_coverage
            + executable_rate
        )
        / 5,
        4,
    )
    metrics = {
        "task_decomposition_recall": task_recall,
        "unexpected_task_rate": unexpected_rate,
        "dependency_accuracy": dependency_recall,
        "interface_contract_coverage": contract_coverage,
        "executable_task_rate": executable_rate,
        "assignment_coverage": assignment_coverage,
        "overall_score": overall_score,
        "elapsed_ms": elapsed_ms,
    }
    return {
        "modules": sorted(modules),
        "dependency_edges": sorted([list(edge) for edge in dependency_edges]),
        "metrics": metrics,
        "passed": all(
            [
                task_recall == 1.0,
                unexpected_rate == 0.0,
                dependency_recall == 1.0,
                contract_coverage == 1.0,
                executable_rate == 1.0,
                assignment_coverage == 1.0,
            ]
        ),
    }


def _evaluate_replan(
    baseline: PlanResult,
    current: PlanResult,
    diff: Any,
    elapsed_ms: float,
) -> dict[str, Any]:
    affected_tasks = set(diff.added_tasks) | {
        change.task_id for change in diff.updated_tasks
    }
    affected_tasks |= {change.task_id for change in diff.dependency_changes}
    affected_precision = _ratio(
        len(affected_tasks & EXPECTED_AFFECTED_TASKS),
        max(len(affected_tasks), 1),
    )
    affected_recall = _ratio(
        len(affected_tasks & EXPECTED_AFFECTED_TASKS),
        len(EXPECTED_AFFECTED_TASKS),
    )
    affected_f1 = _f1(affected_precision, affected_recall)
    added_task_accuracy = _f1(
        _ratio(
            len(set(diff.added_tasks) & {"task_coupon"}), max(len(diff.added_tasks), 1)
        ),
        _ratio(len(set(diff.added_tasks) & {"task_coupon"}), 1),
    )

    order_dependency_change = next(
        (
            change
            for change in diff.dependency_changes
            if change.task_id == "task_order"
        ),
        None,
    )
    dependency_update_detected = (
        order_dependency_change is not None
        and "task_coupon" in order_dependency_change.after
    )
    order_interface_change = next(
        (
            change
            for change in diff.interface_changes
            if change.interface_id == "iface_order"
        ),
        None,
    )
    interface_update_detected = (
        order_interface_change is not None
        and order_interface_change.change_type == "updated"
        and "iface_coupon"
        in (
            order_interface_change.after.dependencies
            if order_interface_change.after
            else []
        )
    )

    baseline_owners = {task.task_id: task.owner_id for task in baseline.tasks}
    current_owners = {task.task_id: task.owner_id for task in current.tasks}
    stable_tasks = {
        task_id
        for task_id in EXPECTED_UNAFFECTED_TASKS
        if baseline_owners.get(task_id) == current_owners.get(task_id)
    }
    owner_stability = _ratio(len(stable_tasks), len(EXPECTED_UNAFFECTED_TASKS))
    overall_score = round(
        (
            affected_f1
            + added_task_accuracy
            + float(dependency_update_detected)
            + float(interface_update_detected)
            + owner_stability
        )
        / 5,
        4,
    )
    metrics = {
        "affected_task_f1": affected_f1,
        "affected_task_precision": affected_precision,
        "affected_task_recall": affected_recall,
        "added_task_accuracy": added_task_accuracy,
        "dependency_update_detected": dependency_update_detected,
        "interface_update_detected": interface_update_detected,
        "unaffected_owner_stability": owner_stability,
        "overall_score": overall_score,
        "elapsed_ms": elapsed_ms,
    }
    return {
        "affected_tasks": sorted(affected_tasks),
        "added_tasks": diff.added_tasks,
        "updated_tasks": [change.model_dump() for change in diff.updated_tasks],
        "dependency_changes": [
            change.model_dump() for change in diff.dependency_changes
        ],
        "interface_changes": [change.model_dump() for change in diff.interface_changes],
        "metrics": metrics,
        "passed": all(
            [
                affected_f1 == 1.0,
                added_task_accuracy == 1.0,
                dependency_update_detected,
                interface_update_detected,
                owner_stability == 1.0,
            ]
        ),
    }


def _dependency_edges(plan: PlanResult) -> set[tuple[str, str]]:
    modules = {task.task_id: task.module for task in plan.tasks}
    return {
        (task.module, modules[dependency])
        for task in plan.tasks
        for dependency in task.depends_on
        if dependency in modules
    }


def _task_is_executable(task: Any) -> bool:
    return all(
        [
            bool(task.owner_id),
            bool(task.allowed_paths),
            bool(task.acceptance_criteria),
            bool(task.interface_requirements),
        ]
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def format_markdown(report: dict[str, Any]) -> str:
    experiment_1 = report["experiment_1_planning"]
    experiment_4 = report["experiment_4_replanning"]
    lines = [
        "# Planning Quality Evaluation",
        "",
        f"- Scenario: `{report['scenario']}`",
        f"- Overall score: `{report['overall_score']}`",
        f"- Passed: `{report['passed']}`",
        "",
        "## Experiment 1: Initial Planning",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {name} | {value} |" for name, value in experiment_1["metrics"].items()
    )
    lines.extend(
        [
            "",
            "## Experiment 4: Coupon Requirement Change",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {name} | {value} |" for name, value in experiment_4["metrics"].items()
    )
    lines.extend(
        [
            "",
            "## Manual Review",
            "",
            "- [ ] Task decomposition is reasonable.",
            "- [ ] Dependencies match the module design.",
            "- [ ] Interface contracts are complete.",
            "- [ ] Affected modules are correctly identified.",
            "- [ ] Unaffected tasks retain their ownership.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Manager Agent planning quality."
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-under", type=float, default=0.9)
    args = parser.parse_args(argv)

    report = run_evaluation(fail_under=args.fail_under)
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else format_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
