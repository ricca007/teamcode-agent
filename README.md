# TeamCode Agent

一个让 3 人小组协作完成软件开发的小平台：一个人用「规划 Agent」把需求拆成任务，每个人在自己的 Git 工作区里用 Coding Agent 写代码，平台自动同步接口文档，前端控制台实时看进度、日志和改动。

> 一句话理解：**提需求 → 自动拆任务 → 各自跑 Agent 写代码 → 实时看进度 → 一键合并**。

## 这个项目能干什么

- **规划**：把一段自然语言需求，自动拆成有依赖关系的任务，分配给对应成员。
- **执行**：每个任务在独立的 Git worktree 里运行 Coding Agent，互不干扰，且只能改自己被允许的目录。
- **接口注册中心**：用 Python AST 自动扫描代码里的函数/类，生成接口文档，大家开发时以它为准，不用猜接口。
- **实时看板**：前端通过 WebSocket 实时看到任务状态、Agent 日志和代码 Diff。
- **合并**：任务完成后，组长一键把任务分支合并回主分支，并自动重扫接口。

## 三个人各自负责什么

| 角色 | 负责内容 | 代码位置 |
| --- | --- | --- |
| A | 规划 Agent（需求拆分、任务分配、重规划） | `backend/app/manager_agent/` |
| B | Agent 运行、Git 工作区、路径权限 | `backend/app/agent_runtime/`、`git_ops/`、`security/` |
| C | 接口注册中心、CLI、实时推送、前端、整合层 | `backend/app/interface_registry/`、`realtime/`、`integration/`、`cli/`、`frontend/` |
| 共同 | 模型、数据契约、文档 | `backend/app/models/`、`schemas/`、`docs/` |

> 完整分工约定见 `CONTRIBUTING.md`。

## 目录结构

```text
.
├── backend/                后端（FastAPI + SQLAlchemy）
│   ├── app/
│   │   ├── manager_agent/      A：规划与重规划
│   │   ├── agent_runtime/      B：Agent 适配器与会话运行
│   │   ├── git_ops/            B：Git worktree 与 Diff
│   │   ├── security/           B：路径权限检查
│   │   ├── interface_registry/ C：AST 提取与接口注册
│   │   ├── realtime/           C：WebSocket 事件
│   │   ├── integration/        C：把 A/B/C 串起来的 REST API
│   │   ├── core/               共享基础设施
│   │   ├── models/             数据库表
│   │   └── schemas/            数据契约（接口返回格式）
│   └── tests/                 后端测试
├── cli/                    C：拉取接口文档的命令行工具
├── frontend/               C：React 前端控制台
├── experiments/            共享的评测脚本
├── scripts/                演示/种子脚本
├── docs/                   接口契约文档
└── docker-compose.yml      一键起后端 + 数据库
```

## 环境要求

先确认你电脑上有这些东西（命令行里运行即可检查）：

| 工具 | 版本要求 | 检查命令 | 说明 |
| --- | --- | --- | --- |
| Python | **3.12 或更高** | `python --version` | 后端用，3.11 装依赖会被拦 |
| Node.js | 18 以上（推荐 22） | `node --version` | 前端用 |
| Git | 任意新版本 | `git --version` | 必须，运行任务依赖它 |
| Docker | 可选 | `docker --version` | 只有「方式二」才需要 |

## 快速开始

有两种方式，**第一次先试「方式一」**，不需要装数据库，几分钟就能看到完整效果。

### 方式一：本地演示（推荐）

#### 第 1 步：装后端依赖

**Windows（PowerShell）：**

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**macOS / Linux（终端）：**

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

#### 第 2 步：生成演示数据

回到仓库根目录，运行种子脚本（它会准备好一个演示项目、队长账号、任务和接口）：

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

脚本最后会打印几行重要信息，**记下来**：

- `项目 ID`：默认 `p_demo`
- `队长账号`：`leader@demo.invalid` + 一个密码（首次登录用）
- `队长 Token`：接口调用时可用

#### 第 3 步：启动后端

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

- `http://127.0.0.1:8000/health` —— 健康检查，返回 `{"status":"ok"}`
- `http://127.0.0.1:8000/docs` —— 自动生成的接口文档（Swagger），**很适合看有哪些接口**

#### 第 4 步：启动前端（另开一个终端）

```bash
cd frontend
npm install
npm run dev
```

然后浏览器打开 **http://localhost:5173**。

> 前端会自动把 `/api` 和 `/ws` 转发到后端 8000 端口，所以后端必须一直开着。

#### 第 5 步：在网页里走完整个流程

1. 打开 http://localhost:5173
2. 用第 2 步打印的队长账号登录（如果不想登录，启动后端前加一行 `$env:TEAMCODE_REQUIRE_AUTH = "0"` / `export TEAMCODE_REQUIRE_AUTH=0`）
3. 在侧栏把项目 ID 改成 `p_demo`
4. 依次体验：**提交需求 → 查看规划 → 分配任务 → 点「运行」→ 看实时日志 → 看 Diff → 提交 → 合并**

### 方式二：Docker 完整环境（Postgres）

如果你想用真实的 PostgreSQL：

```bash
cp .env.example .env
docker compose up --build
```

这会启动数据库和 API（`http://localhost:8000`）。前端仍按上面第 4 步本地 `npm run dev`。

> 注意：Docker 里的后端访问不到你电脑上的项目目录，所以「运行任务」这类需要真实 Git 仓库的演示，还是用方式一更顺。

## 常用命令速查

```bash
# 后端测试 + 静态检查（在 backend/ 下）
pytest
ruff check . ../experiments

# 前端构建 / 检查（在 frontend/ 下）
npm run build   # 类型检查 + 打包
npm run lint    # 代码规范检查
npm test        # 前端回归测试

# 命令行拉取接口文档（需先在仓库根目录执行 pip install -e . 安装 CLI）
teamcode pull-interfaces --project p_demo
```

## 协作规范（要点）

1. 只改自己角色负责的目录。
2. 改了跨模块接口，先更新 `docs/interface_contract.md`。
3. 每人开分支开发，通过 Pull Request 合并，**不要直接推 `main`**。
4. 引入新依赖前先和大家商量。

## 常见问题（FAQ）

**后端报端口被占用怎么办？**

把 `--port 8000` 换成别的端口（比如 `--port 8001`），同时前端也要改代理地址：启动前端时加 `VITE_BACKEND_HTTP=http://127.0.0.1:8001`。

**前端打开是空白 / 一直加载？**

多半是后端没启动，或者后端不在 8000 端口。先确认 `http://127.0.0.1:8000/health` 能打开。

**我的 Python 是 3.11，能跑吗？**

代码其实能在 3.11 上跑，但 `pip install -e ".[dev]"` 会因为版本要求被拦。建议直接装 Python 3.12 最省事。

**登录账号密码在哪？**

运行种子脚本时最后会打印队长账号和密码；如果用了 `--reset`，每次密码可能不同（随机生成），注意看输出。

**改了后端代码要重启吗？**

不需要，启动时带了 `--reload`，保存后会自动重载。前端 `npm run dev` 也是热更新。

## 更多文档

- `docs/interface_contract.md`：接口与事件契约
- `CONTRIBUTING.md`：分工与提交流程
- `backend/README.md`、`frontend/README.md`：各自模块的说明
