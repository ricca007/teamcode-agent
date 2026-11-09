# TeamCode Agent

TeamCode Agent is a multi-agent collaboration platform for small software
development teams. It combines Manager Agent planning, pluggable Coding Agent
execution, Git worktree isolation, interface discovery, and real-time project
visibility.

## Stack

- Backend: FastAPI, SQLAlchemy, PostgreSQL
- Agent orchestration: LangGraph
- Interface registry: Python AST
- Git isolation: Git branches and worktrees
- Frontend: React, TypeScript, Vite
- Realtime updates: WebSocket

## Repository Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── manager_agent/       # A: planning and replanning
│   │   ├── agent_runtime/       # B: adapter and session runtime
│   │   ├── git_ops/             # B: worktree and diff operations
│   │   ├── security/            # B: path permission checks
│   │   ├── interface_registry/  # C: AST extraction and registry
│   │   ├── realtime/            # C: WebSocket event routing
│   │   ├── models/
│   │   └── schemas/
│   └── tests/
├── cli/                         # C: interface pull CLI
├── frontend/                    # C: React dashboard
├── experiments/                 # shared evaluation scripts
├── docs/
│   └── interface_contract.md
└── docker-compose.yml
```

## Local Development

```bash
cp .env.example .env
docker compose up --build
```

The API is available at `http://localhost:8000`, and its health endpoint is
`GET /health`.

To run backend checks directly:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

## Collaboration Rules

1. Work only in the directories assigned to your role.
2. Update `docs/interface_contract.md` before a cross-module contract change.
3. Develop on a dedicated branch and merge through a pull request.
4. Do not push directly to `main`.
5. Discuss new dependencies before adding them.

See `docs/interface_contract.md` for the initial shared API and data contracts.
