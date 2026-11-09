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
| POST | `/api/tasks/{id}/terminate` | Terminate an Agent | B |
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

    def stream_logs(self, session_id: str) -> AsyncIterator[str]: ...

    async def get_changes(self, session_id: str) -> "ChangeSet": ...

    async def pause(self, session_id: str) -> None: ...

    async def terminate(self, session_id: str) -> None: ...
```

Core data structures are defined in `backend/app/schemas/core.py`.

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
