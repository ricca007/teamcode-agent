# TeamCode Agent

> 一个让 3 人小组协作开发软件的多智能体平台 · A multi-agent platform for 3-person software teams
>
> 一句话理解 / In one line：**提需求 → 自动拆任务 → 各自跑 Agent 写代码 → 实时看进度 → 一键合并**
> **Requirements in → tasks out → agents code in isolation → live progress → one-click merge**

## 项目简介 / What it is

TeamCode Agent 是一个面向小团队的协作开发平台：规划 Agent 把需求拆成任务，每个人在自己的 Git 工作区里运行 Coding Agent 写代码，平台自动同步接口文档，前端实时展示进度、日志和改动。

TeamCode Agent is a collaboration platform for small teams: a planning agent breaks requirements into tasks, each member runs a coding agent inside their own Git workspace, the platform keeps interface docs in sync automatically, and a dashboard shows progress, logs, and changes in real time.

## 核心功能 / Features

- **规划 Planning**：把自然语言需求自动拆成有依赖、有负责人的任务。Turns plain-language requirements into tasks with dependencies and owners.
- **隔离执行 Isolated execution**：每个任务在独立 Git worktree 里运行 Agent，只能改自己允许的目录。Each task runs an agent in its own Git worktree and can only touch allowed paths.
- **接口注册中心 Interface registry**：用 AST 自动扫描函数/类，生成接口文档，是团队唯一事实来源。Automatically scans functions/classes with AST to produce the team's single source of truth.
- **实时看板 Realtime dashboard**：WebSocket 实时推送任务状态、Agent 日志和代码 Diff。Streams task status, agent logs, and code diffs over WebSocket.
- **一键合并 One-click merge**：任务完成后组长一键合并回主分支并自动重扫接口。The leader merges finished tasks back to main and re-scans interfaces automatically.

## 三个人各自负责什么 / Team ownership

| 角色 Role | 负责内容 Responsibility | 代码位置 Code |
| --- | --- | --- |
| A | 规划 Agent（需求拆分、任务分配、重规划）Planning agent | `backend/app/manager_agent/` |
| B | Agent 运行、Git 工作区、路径权限 Runtime, git, permissions | `backend/app/agent_runtime/`、`git_ops/`、`security/` |
| C | 接口注册中心、CLI、实时推送、前端、整合层 Registry, CLI, realtime, frontend, integration | `backend/app/interface_registry/`、`realtime/`、`integration/`、`cli/`、`frontend/` |
| 共同 Shared | 模型、数据契约、文档 Models, schemas, docs | `backend/app/models/`、`schemas/`、`docs/` |

> 完整分工约定见 `CONTRIBUTING.md`。See `CONTRIBUTING.md` for the full ownership rules.

## 目录结构 / Repository layout

```text
.
├── backend/                后端 Backend（FastAPI + SQLAlchemy）
│   ├── app/
│   │   ├── manager_agent/      A：规划与重规划 planning
│   │   ├── agent_runtime/      B：Agent 适配器与会话运行 adapter & session
│   │   ├── git_ops/            B：Git worktree 与 Diff
│   │   ├── security/           B：路径权限检查 path permission
│   │   ├── interface_registry/ C：AST 提取与接口注册
│   │   ├── realtime/           C：WebSocket 事件
│   │   ├── integration/        C：把 A/B/C 串起来的 REST API
│   │   ├── core/               共享基础设施 shared infra
│   │   ├── models/             数据库表 DB tables
│   │   └── schemas/            数据契约 data contracts
│   └── tests/                 后端测试 backend tests
├── cli/                    C：拉取接口文档的命令行工具 CLI
├── frontend/               C：React 前端控制台 dashboard
├── experiments/            共享的评测脚本 shared eval scripts
├── scripts/                演示/种子脚本 demo & seed scripts
├── docs/                   接口契约文档 contracts
└── docker-compose.yml      一键起后端 + 数据库 backend + DB
```

## 环境要求 / Requirements

先确认你电脑上有这些东西（命令行运行即可检查）。Check these first:

| 工具 Tool | 版本要求 Version | 检查命令 Check | 说明 Note |
| --- | --- | --- | --- |
| Python | **3.12 或更高 / 3.12+** | `python --version` | 后端用；3.11 装依赖会被拦 |
| Node.js | 18+（推荐 22） | `node --version` | 前端用 frontend |
| Git | 任意新版本 any recent | `git --version` | 必须，运行任务依赖它 required |
| Docker | 可选 optional | `docker --version` | 只有「方式二」需要 |

## 快速开始 / Quick start

有两种方式，**第一次先试「方式一」**，不需要装数据库，几分钟就能看到完整效果。
Try **Method 1** first — no database needed.

### 方式一 Method 1：本地演示 Local demo（推荐 recommended）

#### 第 1 步：装后端依赖 / Install backend deps

**Windows（PowerShell）：**

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**macOS / Linux：**

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

#### 第 2 步：生成演示数据 / Seed demo data

回到仓库根目录运行种子脚本（准备演示项目、队长账号、任务和接口）。Run the seed script from the repo root:

**macOS / Linux：**

```bash
cd ..
python scripts/seed_demo_project.py --reset
```

**Windows：**

```powershell
cd ..
python scripts\seed_demo_project.py --reset --db-url "sqlite+aiosqlite:///C:/teamcode-demo/teamcode-demo.db" --repo-path "C:/teamcode-demo/repo"
```

脚本最后会打印几行重要信息，**记下来**。Note these printed values:

- `项目 ID Project ID`：默认 `p_demo`
- `队长账号 Leader account`：`leader@demo.invalid` + 一个密码 a password
- `队长 Token Leader token`：接口调用时可用 for API calls

#### 第 3 步：启动后端 / Start the backend

**macOS / Linux：**

```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:////tmp/teamcode-demo.db"
uvicorn app.main:app --reload --port 8000
```

**Windows：**

```powershell
cd backend
$env:DATABASE_URL = "sqlite+aiosqlite:///C:/teamcode-demo/teamcode-demo.db"
uvicorn app.main:app --reload --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就说明后端起来了。可以顺手打开：

- `http://127.0.0.1:8000/health` —— 健康检查 health check，返回 `{"status":"ok"}`
- `http://127.0.0.1:8000/docs` —— 自动生成的接口文档 Swagger，适合看有哪些接口

#### 第 4 步：启动前端 / Start the frontend（另开终端）

```bash
cd frontend
npm install
npm run dev
```

然后浏览器打开 **http://localhost:5173**。Open http://localhost:5173.

> 前端会自动把 `/api` 和 `/ws` 转发到后端 8000 端口，所以后端必须一直开着。
> The frontend proxies `/api` and `/ws` to port 8000, so keep the backend running.

#### 第 5 步：在网页里走完整个流程 / Walk the full loop

1. 打开 http://localhost:5173
2. 用第 2 步打印的队长账号登录（不想登录就启动后端前加 `TEAMCODE_REQUIRE_AUTH=0`）
3. 在侧栏把项目 ID 改成 `p_demo`
4. 依次体验：**提交需求 → 查看规划 → 分配任务 → 点「运行」→ 看实时日志 → 看 Diff → 提交 → 合并**

English: log in with the leader account → set project id to `p_demo` → submit requirements → review the plan → assign → click Run → watch logs → view diffs → commit and merge.

### 方式二 Method 2：Docker 完整环境（Postgres）

```bash
cp .env.example .env
docker compose up --build
```

这会启动数据库和 API（`http://localhost:8000`）。前端仍按第 4 步本地 `npm run dev`。
This starts the database and API; still run the frontend locally as in step 4.

> Docker 里的后端访问不到你电脑上的项目目录，做「运行任务」这类真实 Git 仓库演示还是用方式一。
> The Docker backend can't reach your local repo, so use Method 1 for real task-run demos.

## 常用命令 / Common commands

```bash
# 后端测试 + 静态检查（在 backend/ 下）backend tests & lint
pytest
ruff check . ../experiments

# 前端构建 / 检查（在 frontend/ 下）frontend build & check
npm run build   # 类型检查 + 打包 type-check & bundle
npm run lint    # 代码规范检查 lint
npm test        # 前端回归测试 frontend tests

# 命令行拉取接口文档（需先在仓库根目录 pip install -e . 安装 CLI）
teamcode pull-interfaces --project p_demo
```

## 协作规范 / Collaboration rules

1. 只改自己角色负责的目录。Work only in your own role's directories.
2. 改了跨模块接口，先更新 `docs/interface_contract.md`。Update the contract before changing a shared interface.
3. 每人开分支开发，通过 Pull Request 合并，**不要直接推 `main`**。Use branches and PRs; never push to `main` directly.
4. 引入新依赖前先和大家商量。Discuss new dependencies first.

## 常见问题 / FAQ

**后端报端口被占用怎么办？Port already in use?**

把 `--port 8000` 换成别的端口（如 `--port 8001`），同时前端启动时加 `VITE_BACKEND_HTTP=http://127.0.0.1:8001`。
Change `--port 8000` to another port, and add `VITE_BACKEND_HTTP=http://127.0.0.1:8001` when starting the frontend.

**前端打开是空白 / 一直加载？Frontend is blank or loading forever?**

多半是后端没启动，或不在 8000 端口。先确认 `http://127.0.0.1:8000/health` 能打开。
Usually the backend isn't running. Confirm `http://127.0.0.1:8000/health` responds first.

**我的 Python 是 3.11，能跑吗？Can I use Python 3.11?**

代码其实能跑，但 `pip install -e ".[dev]"` 会被版本要求拦。建议直接装 Python 3.12。
The code runs, but the install is blocked by the version requirement. Just install Python 3.12.

**登录账号密码在哪？Where is the login account?**

运行种子脚本时最后会打印队长账号和密码；`--reset` 时密码随机生成，注意看输出。
The seed script prints the leader account and password at the end; with `--reset` the password is random.

**改了后端代码要重启吗？Do I need to restart the backend?**

不需要，启动时带了 `--reload` 会自动重载；前端 `npm run dev` 也是热更新。
No — `--reload` auto-reloads the backend; the frontend is also hot-reloading.

## 更多文档 / More docs

- `docs/interface_contract.md`：接口与事件契约 interface & event contracts
- `CONTRIBUTING.md`：分工与提交流程 ownership & workflow
- `backend/README.md`、`frontend/README.md`：各自模块的说明 per-module notes
