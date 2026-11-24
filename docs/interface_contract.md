# Shared Interface Contract

This document is the initial M0 contract. Update it before changing a shared
API, event, or data structure, and notify all affected owners.

## REST API

All routes below are mounted by `backend/app/main.py`. Authentication is
enforced when `TEAMCODE_REQUIRE_AUTH` is enabled. API keys may be supplied as
an authorization token; the WebSocket also accepts `?token=...`.

### Identity And Teams

| Method | Path | Request body | Purpose | Owner |
| --- | --- | --- | --- | --- |
| GET | `/api/me` | - | Return the current identity | C integration |
| GET | `/api/agents` | - | List available Coding Agents | C integration |
| POST | `/api/auth/register` | `RegisterRequest` | Register a global account | C integration |
| POST | `/api/auth/login` | `LoginRequest` | Log in and obtain a session token | C integration |
| POST | `/api/auth/api-keys` | `ApiKeyCreate` | Create an API key | C integration |
| GET | `/api/auth/api-keys` | - | List the caller's API keys | C integration |
| DELETE | `/api/auth/api-keys/{key_id}` | - | Revoke an API key | C integration |
| GET | `/api/projects` | - | List teams available to the caller | C integration |
| GET | `/api/join-requests/mine` | - | List the caller's join requests | C integration |
| POST | `/api/projects/{project_id}/join-requests` | `JoinTeamRequest` | Request to join a team | C integration |
| POST | `/api/join-requests` | `JoinRequestCreate` | Create a legacy device join request | C integration |
| GET | `/api/join-requests/{request_id}` | - | Read join-request status | C integration |
| GET | `/api/projects/{project_id}/join-requests` | - | List join requests as team leader | C integration |
| POST | `/api/projects/{project_id}/join-requests/{request_id}/approve` | `ApproveJoinRequest` | Approve a join request | C integration |
| POST | `/api/projects/{project_id}/join-requests/{request_id}/reject` | - | Reject a join request | C integration |
| POST | `/api/projects` | `ProjectCreateRequest` | Create a team/project | C integration |
| GET | `/api/projects/{project_id}` | - | Read project details | C integration |
| POST | `/api/projects/{project_id}/members` | `MemberCreateRequest` | Add a project member | C integration |
| GET | `/api/projects/{project_id}/members` | - | List project members | C integration |

### Planning

| Method | Path | Request body | Purpose | Owner |
| --- | --- | --- | --- | --- |
| POST | `/api/projects/{project_id}/requirements` | `RequirementsRequest` | Trigger initial planning or replanning | A planning |
| GET | `/api/projects/{project_id}/plan` | - | Read the active plan and version | A planning |
| GET | `/api/projects/{project_id}/tasks` | - | List project tasks | A planning |
| POST | `/api/projects/{project_id}/tasks/{task_id}/assign` | `AssignTaskRequest` | Assign a task to a member | A planning |

### Task Runtime

| Method | Path | Request body | Purpose | Owner |
| --- | --- | --- | --- | --- |
| POST | `/api/tasks/{task_id}/run` | `RunRequest` | Start a Coding Agent session | B runtime |
| POST | `/api/tasks/{task_id}/pause` | - | Pause a session | B runtime |
| POST | `/api/tasks/{task_id}/resume` | - | Resume a session | B runtime |
| POST | `/api/tasks/{task_id}/terminate` | - | Terminate a session | B runtime |
| GET | `/api/tasks/{task_id}/status` | - | Read the latest session status | B runtime |
| GET | `/api/tasks/{task_id}/logs` | - | Read ordered session logs | B runtime |
| GET | `/api/tasks/{task_id}/changes` | - | Read captured file changes | B runtime |
| POST | `/api/tasks/{task_id}/messages` | `MessageRequest` | Continue the active agent conversation | B runtime |
| POST | `/api/projects/{project_id}/tasks/{task_id}/merge` | `MergeTaskRequest` | Merge a task branch and rescan interfaces | B runtime + C integration |
| POST | `/api/tasks/{task_id}/commit` | `CommitRequest` | Commit authorized task changes | B runtime |

### Interface Registry And System

| Method | Path | Request body | Purpose | Owner |
| --- | --- | --- | --- | --- |
| GET | `/api/projects/{project_id}/interfaces` | - | List interfaces or pull Markdown | C interface registry |
| GET | `/api/interfaces/{interface_id}` | - | Read one interface | C interface registry |
| POST | `/api/projects/{project_id}/interfaces/refresh` | `RefreshRequest` | Trigger an interface rescan | C interface registry |
| GET | `/health/interfaces` | - | Read watcher/registry health | C interface registry |
| GET | `/health` | - | API liveness | Shared |
| GET | `/health/database` | - | Database readiness | Shared |

The interfaces endpoint supports `?format=json` and `?format=markdown`.

### WebSocket

| Protocol | Path | Authentication | Purpose | Owner |
| --- | --- | --- | --- | --- |
| WebSocket | `/ws/projects/{project_id}` | Optional `?token=...` | Receive project realtime events | C realtime |

The client may send `ping`; the server responds with a `pong` event.

## Request Models

| Model | Fields |
| --- | --- |
| `RegisterRequest` | `name`, `email`, `password` |
| `LoginRequest` | `email`, `password` |
| `ApiKeyCreate` | `name`, optional `project_id` |
| `ProjectCreateRequest` | `name`, `repo_path`, optional `project_id`, `owner_id`, `owner_name`, `owner_email` |
| `MemberCreateRequest` | `user_id`, optional `name`, `email`, `role` |
| `JoinTeamRequest` | optional `areas` |
| `JoinRequestCreate` | `project_id`, `display_name`, `device_id`, `device_secret` |
| `ApproveJoinRequest` | optional `areas` |
| `RequirementsRequest` | `requirements`, `members`, `roles`, `max_tasks`, `mode` |
| `AssignTaskRequest` | `user_id` |
| `RunRequest` | optional `actor_id`, `agent_name`, `adapter_name`, `prompt`, `context`; `base_branch` |
| `MessageRequest` | `message`, optional `actor_id` |
| `MergeTaskRequest` | `message`, `base_branch` |
| `CommitRequest` | optional `actor_id`; required `message` |
| `RefreshRequest` | optional `root`; `include_tests` |

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

- `task.updated`: `IntegrationService`; payload contract owned by A planning
- `agent.log` and `code.changed`: `IntegrationService`; payload contract owned by B runtime
- `interface.updated`: interface registry watcher/refresh or integration merge; owned by C

All events use the envelope above. `task_id` may be `null` for project-level
events. Members who are not team leaders receive only `agent.log` and
`code.changed` events for tasks they own.

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
