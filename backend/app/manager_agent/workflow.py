from functools import lru_cache
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.manager_agent.repository import analyze_repository
from app.manager_agent.requirements import group_requirements, normalize_requirements
from app.manager_agent.tasks import (
    assign_tasks,
    decompose_tasks,
    generate_interface_contracts,
    infer_dependencies,
)
from app.schemas.planning import (
    InterfaceContractDraft,
    PlannedTask,
    PlanningRequest,
    PlanResult,
    RepositorySnapshot,
)


class PlanningState(TypedDict, total=False):
    request: PlanningRequest
    normalized_requirements: list[str]
    repository: RepositorySnapshot
    tasks: list[PlannedTask]
    interface_contracts: list[InterfaceContractDraft]
    plan: PlanResult


def parse_requirements_node(state: PlanningState) -> dict[str, object]:
    return {"normalized_requirements": normalize_requirements(state["request"].requirements)}


def analyze_repository_node(state: PlanningState) -> dict[str, object]:
    return {"repository": analyze_repository(state["request"].repo_path)}


def decompose_tasks_node(state: PlanningState) -> dict[str, object]:
    request = state["request"]
    grouped = group_requirements(state["normalized_requirements"])
    return {
        "tasks": decompose_tasks(
            project_id=request.project_id,
            grouped=grouped,
            max_tasks=request.max_tasks,
        )
    }


def infer_dependencies_node(state: PlanningState) -> dict[str, object]:
    return {"tasks": infer_dependencies(state["tasks"])}


def generate_contracts_node(state: PlanningState) -> dict[str, object]:
    tasks, contracts = generate_interface_contracts(state["tasks"])
    return {"tasks": tasks, "interface_contracts": contracts}


def assign_tasks_node(state: PlanningState) -> dict[str, object]:
    request = state["request"]
    tasks = assign_tasks(state["tasks"], request.members)
    return {
        "tasks": tasks,
        "plan": PlanResult(
            project_id=request.project_id,
            normalized_requirements=state["normalized_requirements"],
            repository=state["repository"],
            tasks=tasks,
            interface_contracts=state["interface_contracts"],
        ),
    }


@lru_cache
def build_planning_graph():
    graph = StateGraph(PlanningState)
    graph.add_node("parse_requirements", parse_requirements_node)
    graph.add_node("analyze_repository", analyze_repository_node)
    graph.add_node("decompose_tasks", decompose_tasks_node)
    graph.add_node("infer_dependencies", infer_dependencies_node)
    graph.add_node("generate_contracts", generate_contracts_node)
    graph.add_node("assign_tasks", assign_tasks_node)

    graph.add_edge(START, "parse_requirements")
    graph.add_edge("parse_requirements", "analyze_repository")
    graph.add_edge("analyze_repository", "decompose_tasks")
    graph.add_edge("decompose_tasks", "infer_dependencies")
    graph.add_edge("infer_dependencies", "generate_contracts")
    graph.add_edge("generate_contracts", "assign_tasks")
    graph.add_edge("assign_tasks", END)
    return graph.compile()


def create_plan(request: PlanningRequest) -> PlanResult:
    result = build_planning_graph().invoke({"request": request})
    return PlanResult.model_validate(result["plan"])
