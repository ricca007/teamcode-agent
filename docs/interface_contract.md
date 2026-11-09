# Shared Interface Contract

This document is the initial M0 contract. Update it before changing a shared
API, event, or data structure, and notify all affected owners.

## REST API

| Method | Path | Purpose | Owner |
| --- | --- | --- | --- |
| POST | `/api/projects` | Create a project | A |
| POST | `/api/projects/{id}/members` | Invite a member and assign a role | A |
| POST | `/api/projects/{id}/requirements` | Submit requirements and trigger planning | A |
| GET | `/api/projects/{id}/plan` | Read the current plan and version | A |
| GET | `/api/projects/{id}/tasks` | List project tasks | A |
| POST | `/api/tasks/{id}/run` | Create a worktree and start an Agent | B |
| POST | `/api/tasks/{id}/pause` | Pause an Agent | B |
| POST | `/api/tasks/{id}/resume` | Resume an Agent | B |
| POST | `/api/tasks/{id}/terminate` | Terminate an Agent | B |
| POST | `/api/tasks/{id}/commit` | Commit authorized task changes | B |
| GET | `/api/tasks/{id}/status` | Read session status | B |
| GET | `/api/tasks/{id}/logs` | Read session logs | B |
| GET | `/api/tasks/{id}/changes` | Read file changes and commits | B |
| GET | `/api/projects/{id}/interfaces` | List interfaces or pull Markdown | C |
| GET | `/api/interfaces/{interface_id}` | Read one interface | C |
| POST | `/api/projects/{id}/interfaces/refresh` | Trigger an interface rescan | C |
| WS | `/ws/projects/{id}` | Receive project realtime events | C route owner |

The interfaces endpoint supports `?format=json` and `?format=markdown`.

## Realtime Event Envelope

```json
{
  "type": "task.updated | agent.log | interface.updated | code.changed",
  "project_id": "p_001",
  "task_id": "t_003",
  "payload": {},
  "ts": "2026-01-01T10:00:00Z"
}
```

Event ownership:

- `task.updated`: A
- `agent.log` and `code.changed`: B
- `interface.updated`: C

## Coding Agent Adapter Protocol

```python
from pathlib import Path
from typing import AsyncIterator, Protocol

class CodingAgentAdapter(Protocol):
    async def start_session(
        self, task: "TaskSpec", workspace: Path, env: dict[str, str]
    ) -> "SessionInfo": ...

    async def send_task(
        self, session_id: str, prompt: str, context: dict
    ) -> None: ...

    async def get_status(self, session_id: str) -> "AgentStatus": ...

    def stream_logs(self, session_id: str) -> AsyncIterator["AgentLog"]: ...

    async def get_changes(self, session_id: str) -> "ChangeSet": ...

    async def pause(self, session_id: str) -> None: ...

    async def resume(self, session_id: str) -> None: ...

    async def terminate(self, session_id: str) -> None: ...
```

Core data structures are defined in `backend/app/schemas/core.py`. The runtime
schema also defines `AgentLog`, `GitWorkspace`, `ExecutionResult`, and
`task_prompt`; `TaskSpec` includes `base_branch`, and `SessionInfo` includes
`ended_at`.

## Database Model

The initial Alembic migration creates these tables:

| Table | Purpose |
| --- | --- |
| `users` | Platform users and their global roles |
| `projects` | Project metadata and owning repository path |
| `project_members` | Per-project member roles |
| `tasks` | Development tasks, allowed paths, and workspace state |
| `task_dependencies` | Directed task dependency edges |
| `agent_sessions` | Coding Agent execution sessions |
| `agent_logs` | Ordered session log records |
| `code_changes` | Captured diffs and commit metadata |
| `interface_contracts` | Versioned Python interface records |

Status and role values are stored using their lowercase public values, for
example `in_progress` and `member`.

Run migrations from `backend/`:

```bash
alembic upgrade head
```

Docker Compose applies pending migrations before starting the API.

## Manager Agent Planning

The stable planning entry point is:

```python
from app.manager_agent import create_plan
from app.schemas import PlanningRequest

plan = create_plan(request)
```

`PlanningRequest` contains the project ID, natural-language requirements,
repository path, member areas, and optional task limit. `PlanResult` contains
normalized requirements, a repository snapshot, assigned tasks, and interface
contract drafts.

The LangGraph workflow has six ordered stages:

1. `parse_requirements`
2. `analyze_repository`
3. `decompose_tasks`
4. `infer_dependencies`
5. `generate_contracts`
6. `assign_tasks`

The M0 implementation is deterministic and does not require an external model.
Model-backed planning can replace individual node implementations without
changing the graph or `create_plan()` contract.

### Incremental Replanning

Use `replan()` with the previous `PlanResult` and a complete updated planning
request:

```python
from app.manager_agent import replan

result = replan(previous_plan, updated_request)
```

`ReplanResult` contains the new plan and a structured `PlanDiff` covering
added, removed, updated, and unchanged tasks, dependency changes, interface
changes, and impact notes. Each replan increments the plan version and keeps
existing task ownership when the member is still available.

## Planning Evaluation

Run the Experiment 1 and Experiment 4 evaluation from the repository root:

```bash
python experiments/eval_planning.py --format markdown
python experiments/eval_planning.py --format json --output experiments/results/planning.json
```

The script exercises the online-store baseline and a coupon requirement change.
It reports task, dependency, contract, assignment, replanning impact, owner
stability, and elapsed-time metrics. A non-zero exit status signals an
automated threshold failure.
