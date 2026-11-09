# ruff: noqa: E402

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.eval_planning import format_markdown, run_evaluation


def test_planning_evaluation_passes_structural_expectations() -> None:
    report = run_evaluation()

    assert report["passed"] is True
    assert report["experiment_1_planning"]["metrics"]["task_decomposition_recall"] == 1.0
    assert report["experiment_1_planning"]["metrics"]["dependency_accuracy"] == 1.0
    assert report["experiment_4_replanning"]["affected_tasks"] == [
        "task_coupon",
        "task_order",
    ]
    assert report["experiment_4_replanning"]["metrics"]["interface_update_detected"] is True
    assert report["experiment_4_replanning"]["metrics"]["unaffected_owner_stability"] == 1.0


def test_markdown_report_contains_both_experiments() -> None:
    report = run_evaluation()
    markdown = format_markdown(report)

    assert "# Planning Quality Evaluation" in markdown
    assert "Experiment 1: Initial Planning" in markdown
    assert "Experiment 4: Coupon Requirement Change" in markdown
