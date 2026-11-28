# TeamCode Agent

A multi-agent collaboration platform for small software teams (3–5 people).
It connects requirement breakdown, task assignment, Coding Agent execution,
interface-contract synchronization, and code-change review into one observable
pipeline. Multiple Coding Agents work in isolated worktrees while sharing a
single source of truth for interfaces.

Stack: FastAPI + SQLAlchemy + PostgreSQL / SQLite, LangGraph, Python AST,
Git Worktree, React + TypeScript + Vite, WebSocket.

---

## Contents

1. [Problems We Solve](#1-problems-we-solve)
2. [Solution](#2-solution)
3. [Architecture](#3-architecture)
4. [Environment Setup](#4-environment-setup)
5. [Running the Project](#5-running-the-project)
6. [Testing](#6-testing)
7. [Localization](#7-localization)
8. [Team Roles](#8-team-roles)
9. [Repository Layout](#9-repository-layout)
10. [Collaboration Docs](#10-collaboration-docs)

---

## 1. Problems We Solve

When a small team runs several Coding Agents (Claude Code, Codex, Aider, etc.)
in parallel, the same problems keep appearing:

| Problem | Symptom |
| --- | --- |
| Planning by hand | Requirements are split inconsistently, dependencies live in chat, progress is invisible |
| Interface drift | One member changes a signature while another still codes against the old one; integration breaks late |
| Workspace collisions | Agents edit the same checkout, overwriting each other's uncommitted changes |
| Path violations | An Agent edits directories outside its scope, or even runs `git push` |
| Opaque execution | No shared view of task state, Agent output, or changed files |
| Stale documentation | Hand-written interface docs rot; Agents cannot reliably "pull" the current contract |

TeamCode aims to **put planning, execution, interface contracts, and change
review into one observable console**, and to isolate each Agent with Git
worktrees plus `allowed_paths` whitelists.

---

## 2. Solution

### 2.1 Core Ideas

1. **Manager Agent plans.** Natural-language requirements go through a six-stage
   LangGraph workflow that produces tasks, dependencies, owners, and interface
   contract drafts.
2. **The interface registry is the single source of truth.** A Python AST scan
   extracts function/method/class signatures, parameters, return types,
   docstrings, and versions. HTTP, CLI, MCP, and Agent prompts all reuse the
   same Markdown.
3. **One worktree per task.** Each run creates an isolated branch and worktree;
   `allowed_paths` is validated before changes are accepted.
4. **Everything is observable.** Session status, logs, file changes, and
   interface updates stream to the console over WebSocket.
5. **Humans stay in the loop.** Leaders can reassign tasks, approve members,
   inspect diffs, and merge manually.

### 2.2 Capability Map

| Capability | Implementation |
| --- | --- |
| Requirement parsing, task decomposition, dependency analysis, assignment | `backend/app/manager_agent/` (LangGraph workflow) |
| Incremental replanning after requirement changes | `manager_agent/replanning.py` |
| Agent adapters (claude / codex / aider / dsh / custom) | `backend/app/agent_runtime/` |
| Session state machine, pause/resume/terminate, log persistence and streaming | `agent_runtime/session_manager.py`, `log_stream.py` |
| Git branch / worktree isolation, diff, commit, merge | `backend/app/git_ops/` |
| `allowed_paths` permission checks | `backend/app/security/path_policy.py` |
| AST extraction, versions, Markdown rendering, file watcher | `backend/app/interface_registry/` |
| Pullable docs: REST / CLI / MCP | `interface_registry/api.py`, `cli/teamcode.py`, `cli/mcp_server.py` |
| Realtime events (task / log / change / interface) | `backend/app/realtime/` |
| Accounts, join requests, approvals, API keys | `backend/app/integration/auth.py`, `service.py` |
| Integration REST API (projects, tasks, members, merge) | `backend/app/integration/api.py` |
| React console (6 views + ZH/EN switch) | `frontend/src/` |

---

## 3. Architecture

### 3.1 Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                  React Console (Vite + TS)                  │
│  Task board / Agent sessions / Interfaces / Changes /       │
│  API keys / Team                                            │
│      REST client            WebSocket client   ZH|EN switch │
└───────────────┬─────────────────────┬───────────────────────┘
                │ /api (proxy)        │ /ws/projects/{id}
┌───────────────▼─────────────────────▼───────────────────────┐
│                      FastAPI Backend                        │
│                                                             │
│  integration  ── auth / projects / tasks / members / merge  │
│      │                                                      │
│      ├── manager_agent (A)   LangGraph planning & replan    │
│      ├── agent_runtime (B)   Adapters + sessions + logs     │
│      ├── git_ops (B)         Worktree / branch / diff       │
│      ├── security (B)        allowed_paths validation       │
│      ├── interface_registry (C)  AST / versions / Markdown  │
│      └── realtime (C)        WebSocket event bus            │
└───────────────┬─────────────────────────────────────────────┘
                │
      ┌─────────▼─────────┐        ┌──────────────────────┐
      │ PostgreSQL /      │        │ Target Git repo      │
      │ SQLite            │        │ .teamcode/worktrees/ │
      └───────────────────┘        └──────────────────────┘

Additionally: the CLI (teamcode pull-interfaces) and the MCP server reuse the
interface registry directly.
```

### 3.2 Task Execution Flow

```text
Click Run in the console (sends the current locale)
  → POST /api/tasks/{id}/run
  → integration layer builds TaskSpec + Agent prompt + interface Markdown
  → git_ops creates a branch + worktree
  → agent_runtime runs the adapter (real CLI or mock)
  → logs are persisted and streamed as agent.log
  → on completion, collect changed files; security validates allowed_paths
  → persist code_changes and publish code.changed / task.updated
  → console refreshes sessions, logs, and diff
```

- The prompt explicitly constrains the Agent: only edit allowed paths inside the
  worktree, never commit or push, and run the relevant tests itself.
- Prompts and the injected interface Markdown support both Chinese and English,
  following the current UI language (see section 7).
- Merging is triggered manually by the leader in the Team view; the interface
  registry is rescanned after a merge.

### 3.3 Interface Source-of-Truth Flow

```text
Source change → watcher detects .py → AST extraction → content hash compare
  → on change: version + 1 and snapshot saved → WS publishes interface.updated
HTTP / CLI / MCP / Agent prompt  ←  the same render_markdown()
```

### 3.4 Realtime Events

WebSocket endpoint: `/ws/projects/{project_id}`

| Event | Producer | Purpose |
| --- | --- | --- |
| `task.updated` | integration layer | Task status, owner, replan version |
| `agent.log` | agent_runtime | Per-line session logs |
| `code.changed` | git_ops / integration | File changes and diff |
| `interface.updated` | interface_registry | Interface added / changed / deleted |

### 3.5 Main Tables

`users`, `projects`, `project_members`, `tasks`, `task_dependencies`,
`interface_contracts` (with version state), `agent_sessions`, `agent_logs`,
`code_changes`, plus auth tables: `auth_sessions`, `api_keys`, `join_requests`.

> Shared contract: [`docs/interface_contract.md`](docs/interface_contract.md).
> Interface registry details: [`docs/interface_registry.md`](docs/interface_registry.md).

---

## 4. Environment Setup

### 4.1 Requirements

| Component | Version / Requirement |
| --- | --- |
| Python | ≥ 3.12 (CI uses 3.12 for backend and CLI) |
| Node.js | 22 (CI uses 22, npm included) |
| PostgreSQL | 16 (`docker-compose.yml` uses `postgres:16-alpine`) |
| SQLite | Used by local demos and backend tests (`aiosqlite`) |
| Docker | Optional, for one-command PostgreSQL + API |

Real Coding Agents (optional): install and log in to `claude`, `codex`, or
`aider` yourself. If none is installed, use the `mock` mode for demos (5.3).

### 4.2 Environment Variables

Copy the template:

```bash
cp .env.example .env
```

The backend loads `.env` in this order (explicit environment variables win):
current directory `.env` → `backend/.env` → repository root `.env`.
`TEAMCODE_ENV_FILE` can point to an explicit file.

**Database and auth**

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://teamcode:teamcode@localhost:5432/teamcode` | Backend database URL |
| `TEAMCODE_REQUIRE_AUTH` | `1` | Set to `0` to disable auth for local debugging/demos only |
| `TEAMCODE_AUTH_SECRET` | none | Required when auth is enabled; must be long and random, the default value is rejected |

**Coding Agent selection**

| Variable | Default | Notes |
| --- | --- | --- |
| `TEAMCODE_AGENT` | `claude` | Default Agent when Run does not specify one |
| `TEAMCODE_EXPOSE_MOCK` | `0` | Set to `1` to show `mock` in the console's Agent dropdown |
| `TEAMCODE_AGENTS` | none | JSON object for custom Agents |
| `TEAMCODE_CLAUDE_COMMAND` / `TEAMCODE_CODEX_COMMAND` / `TEAMCODE_AIDER_COMMAND` | built-in defaults | Override the corresponding CLI command |
| `TEAMCODE_AGENT_TIMEOUT` / `TEAMCODE_CHAT_TIMEOUT` | `300` | Agent run and follow-up chat timeouts (seconds) |
| `TEAMCODE_MERGE_DELETE_BRANCH` | `0` | Delete the task branch after merge |

**Frontend**

| Variable | Default | Notes |
| --- | --- | --- |
| `VITE_BACKEND_HTTP` | `http://127.0.0.1:8000` | Vite dev proxy target |
| `VITE_PROJECT_ID` | `p_001` | Initial project ID (after login the account's projects are used) |
| `VITE_API_BASE` / `VITE_WS_BASE` | same origin | Set explicitly when deploying on a separate domain |

---

## 5. Running the Project

### 5.1 Docker: PostgreSQL + API (recommended full path)

```bash
cp .env.example .env
# For local debugging you may set TEAMCODE_REQUIRE_AUTH=0.
# If auth stays enabled, replace TEAMCODE_AUTH_SECRET with a long random value.
docker compose up --build
```

What starts:

- PostgreSQL 16 on `localhost:5432`
- FastAPI on `http://localhost:8000` (runs `alembic upgrade head` first)
- Health checks: `GET /health`, `GET /health/database`
- Swagger UI: `http://localhost:8000/docs`

> `docker-compose.yml` contains **only api + db, not the frontend**.
> Start the frontend separately (5.4).

### 5.2 Run the Backend Locally (existing PostgreSQL)

```bash
# From the repository root
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e "./backend[dev]"   # backend + test dependencies
pip install -e .                  # optional: teamcode CLI

cd backend
export DATABASE_URL="postgresql+asyncpg://teamcode:teamcode@localhost:5432/teamcode"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 5.3 SQLite + Mock One-Command Demo (no PostgreSQL, no real Agent)

`scripts/seed_demo_project.py` prepares a temporary Git repository, creates the
schema, and generates 6 tasks and 11 interfaces. It also runs one task through
`MockAdapter`, producing a session, logs, and a diff.

```bash
# From the repository root
TEAMCODE_AGENT=mock TEAMCODE_SEED_PASSWORD=demo123456 \
  .venv/bin/python scripts/seed_demo_project.py --reset --lang en --run

# Start the backend against the same database file
cd backend
DATABASE_URL="sqlite+aiosqlite:////tmp/teamcode-demo.db" \
TEAMCODE_REQUIRE_AUTH=0 \
TEAMCODE_AGENT=mock \
TEAMCODE_EXPOSE_MOCK=1 \
  ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Notes:

- `--lang en` seeds English data (project name, task descriptions, interface
  docstrings, placeholder members `Role A/B/C`). Omit it for Chinese data.
- The demo account is printed by the seed script: `leader@demo.invalid`,
  password from `TEAMCODE_SEED_PASSWORD` (demo only, never for real data).
- On Windows, prefer explicit ASCII paths to avoid Git subprocess issues:
  ```bash
  ... --db-url "sqlite+aiosqlite:///D:/teamcode-demo.db" --repo-path "D:/teamcode-demo-repo"
  ```
  `DATABASE_URL` for the backend must match `--db-url`.

**How to enable mock mode** (disabled and hidden by default):

1. Show `mock` in the console dropdown: set `TEAMCODE_EXPOSE_MOCK=1` on the backend.
2. Make Run default to mock: set `TEAMCODE_AGENT=mock` on the backend.
3. Or call the API with `{"agent_name": "mock"}` in the request body.

Mock writes a real file at `allowed_paths[0]/generated_service.py` and produces
a unified diff. Its content follows `locale` (Chinese or English), and it never
commits or pushes.

### 5.4 Frontend Console

```bash
cd frontend
npm ci            # or npm install
npm run dev
```

- Open `http://127.0.0.1:5173`
- Vite proxies `/api` and `/ws` to `http://127.0.0.1:8000` (override with
  `VITE_BACKEND_HTTP`)
- Production build: `npm run build` (output in `frontend/dist/`)

Views: Task board, Agent sessions, Interfaces, Code changes, API keys, Team.
A language toggle (`ZH` / `EN`) sits in the top-right corner.

### 5.5 CLI and MCP (interface docs for Coding Agents)

Install the root package to get the `teamcode` command:

```bash
pip install -e .

teamcode pull-interfaces --project p_demo --output interfaces.md
teamcode pull-interfaces --project p_demo --format json
teamcode pull-interfaces --project p_demo --offline \
  --db-url "sqlite+aiosqlite:////tmp/teamcode-demo.db"
```

MCP (stdio, JSON-RPC): `python -m cli.mcp_server --db-url <DATABASE_URL>`

---

## 6. Testing

### 6.1 Backend

```bash
cd backend
pip install -e ".[dev]"
ruff check . ../experiments
pytest
```

- Backend tests use SQLite (`aiosqlite`) and do not require PostgreSQL.
- CI: `.github/workflows/backend-ci.yml` (Python 3.12, ruff + pytest).

**Windows tip**: if your home directory contains non-ASCII characters, some Git
subprocesses fail on encoding. Point temp paths to ASCII directories:

```bash
TEMP=D:/teamcode-tmp TMP=D:/teamcode-tmp pytest --basetemp=D:/teamcode-tmp/pytest
```

### 6.2 Frontend

```bash
cd frontend
npm ci
npm run lint
npm test          # node --test regression tests for client / store / format
npm run build     # tsc --noEmit + vite build
```

CI: `.github/workflows/frontend-ci.yml` (Node 22, lint + test + build).

### 6.3 Evaluation Scripts

```bash
.venv/bin/python experiments/eval_planning.py
.venv/bin/python experiments/eval_interfaces.py
```

They evaluate planning quality and AST extraction quality respectively, writing
results to `experiments/reports/`.

---

## 7. Localization

- The console defaults to English. The `ZH` / `EN` toggle in the top-right
  corner persists the choice in `localStorage("tc_locale")`.
- UI copy, date formats, status/type labels, and copied/downloaded interface
  Markdown all follow the selected language.
- When you click Run, the frontend sends the current language as `locale`:
  - Agent task prompts, execution constraints, and the injected interface
    Markdown use that language;
  - Unknown values fall back to Chinese; CLI and seed default to Chinese.
- Stored server-side data (member names, task text, logs) is not translated by
  the toggle. Seed English data with `--lang en` when needed.

---

## 8. Team Roles

| Role | Responsibilities | Main directories | Experiments |
| --- | --- | --- | --- |
| **A** Planning | Manager Agent, task decomposition, dependency analysis, interface contract generation, dynamic replanning | `backend/app/manager_agent/`, `backend/app/schemas/planning.py`, `experiments/eval_planning.py` | 1, 4 |
| **B** Runtime & security | Agent adapters, session runtime, logs, Git worktrees, path permissions, execution API | `backend/app/agent_runtime/`, `backend/app/git_ops/`, `backend/app/security/`, `backend/app/api/execution.py` | 2 |
| **C** Interfaces & frontend | AST extraction, interface registry, CLI/MCP, realtime, React console, integration layer | `backend/app/interface_registry/`, `backend/app/realtime/`, `backend/app/integration/`, `cli/`, `frontend/` | 3, 5 |

Shared items (data models, schemas, contract docs) are maintained together;
A maintains the initial version. Cross-module contract changes must update
[`docs/interface_contract.md`](docs/interface_contract.md) first.

Collaboration rules:

1. Only change directories you own; align on the contract before cross-module edits.
2. One branch per task: `feature/<area>-<desc>`, `fix/...`, `docs/...`.
3. Merge through pull requests; never push directly to `main`.
4. Behavior changes require tests.
5. Coding Agents must run `teamcode pull-interfaces` or read the contract before coding.

---

## 9. Repository Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── integration/          # C: REST integration, auth, project/task orchestration
│   │   ├── manager_agent/        # A: LangGraph planning and replanning
│   │   ├── agent_runtime/        # B: adapters / sessions / logs / mock
│   │   ├── git_ops/              # B: worktree / branch / diff / merge
│   │   ├── security/             # B: allowed_paths validation
│   │   ├── interface_registry/   # C: AST extraction / versions / Markdown / watcher
│   │   ├── realtime/             # C: WebSocket event bus
│   │   ├── models/               # shared ORM models
│   │   ├── schemas/              # shared Pydantic schemas
│   │   ├── api/                  # earlier execution API (B)
│   │   ├── config.py / db.py / main.py
│   ├── alembic/                  # database migrations
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── cli/                          # C: teamcode pull-interfaces / MCP server
├── frontend/                     # C: React + TS console (with i18n)
│   ├── src/i18n/                 # bilingual copy and locale state
│   ├── src/components/           # 6 views and shared components
│   └── tests/                    # node --test regression tests
├── experiments/
│   ├── eval_planning.py          # A: planning evaluation
│   ├── eval_interfaces.py        # C: interface extraction evaluation
│   └── fixtures/
│       ├── shop_app/             # Chinese demo repository
│       └── shop_app_en/          # English demo repository
├── scripts/
│   ├── seed_demo_project.py      # one-command demo data (--lang zh|en)
│   └── *.py                      # Claude stream wrapper / interface verification
├── docs/
│   ├── interface_contract.md     # shared REST / WS / Adapter contract
│   └── interface_registry.md
├── .github/workflows/            # backend / frontend CI
├── docker-compose.yml
└── .env.example
```

---

## 10. Collaboration Docs

- [`CONTRIBUTING.md`](CONTRIBUTING.md): branching, PRs, ownership
- [`docs/interface_contract.md`](docs/interface_contract.md): REST, WebSocket, Adapter Protocol
- [`docs/interface_registry.md`](docs/interface_registry.md): interface registry and CLI/MCP
- [`backend/README.md`](backend/README.md), [`frontend/README.md`](frontend/README.md): subproject notes
