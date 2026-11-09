from pathlib import Path

from app.manager_agent import build_planning_graph, create_plan
from app.manager_agent.requirements import classify_requirement, normalize_requirements
from app.schemas import PlanningRequest, TeamMemberSpec


def _building_request(repo_path: Path) -> PlanningRequest:
    return PlanningRequest(
        project_id="project_shop",
        requirements=(
            "Build an online store.\n"
            "- Users can register, log in, and manage profiles.\n"
            "- Products can be searched and managed.\n"
            "- Orders can be created and paid."
        ),
        repo_path=str(repo_path),
        members=[
            TeamMemberSpec(member_id="member_a", name="A", areas=["user"]),
            TeamMemberSpec(member_id="member_b", name="B", areas=["order"]),
            TeamMemberSpec(member_id="member_c", name="C", areas=["product"]),
        ],
    )


def test_planning_graph_contains_all_stages() -> None:
    node_names = set(build_planning_graph().get_graph().nodes)

    assert {
        "parse_requirements",
        "analyze_repository",
        "decompose_tasks",
        "infer_dependencies",
        "generate_contracts",
        "assign_tasks",
    }.issubset(node_names)


def test_create_plan_builds_online_store_tasks(tmp_path: Path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "models.py").write_text(
        "class Product:\n    pass\n\ndef get_user():\n    pass\n",
        encoding="utf-8",
    )

    plan = create_plan(_building_request(tmp_path))

    tasks = {task.module: task for task in plan.tasks}
    assert set(tasks) == {"user", "product", "order"}
    assert set(tasks["order"].depends_on) == {tasks["user"].task_id, tasks["product"].task_id}
    assert {task.owner_id for task in plan.tasks} == {"member_a", "member_b", "member_c"}
    assert all(task.interface_requirements for task in plan.tasks)
    assert len(plan.interface_contracts) == 3
    assert plan.repository.modules[0].classes == ["Product"]


def test_create_plan_is_deterministic(tmp_path: Path) -> None:
    request = _building_request(tmp_path)

    assert create_plan(request) == create_plan(request)


def test_repository_analysis_ignores_vendor_directories(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("def hidden():\n    pass\n")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    plan = create_plan(_building_request(tmp_path))

    files = {module.file_path for module in plan.repository.modules}
    assert files == {"app/main.py"}
    assert len(plan.repository.parse_errors) == 1


def test_chinese_requirements_are_split_and_classified() -> None:
    requirements = normalize_requirements("开发网店。用户登录。商品管理。订单支付。")

    assert requirements == ["开发网店。", "用户登录。", "商品管理。", "订单支付。"]
    assert classify_requirement(requirements[1]) == ["user"]
    assert classify_requirement(requirements[2]) == ["product"]
    assert classify_requirement(requirements[3]) == ["order"]
