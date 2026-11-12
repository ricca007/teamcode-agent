# TeamCode Agent

TeamCode Agent 是面向小组软件开发的多 Agent 协作平台，将任务规划、Coding Agent 执行、独立工作区、代码审查和接口共享整合到一个工作台。

## 主要功能

- 使用 LangGraph 生成任务、分配负责人、分析依赖，并根据新需求进行增量重规划。
- 通过项目成员 token 区分组长和成员，限制任务操作权限。
- 通过 Adapter 接入 CLI Coding Agent，也提供用于联调演示的 MockAdapter。
- 每个任务使用独立 Git 分支和 worktree，支持路径校验、Diff、真实测试、提交和组长审查合并。
- 使用 Python AST 自动提取接口，支持文件监听、版本历史和 Markdown 导出。
- 通过 REST、CLI 和 stdio MCP 向成员及其 Agent 提供最新接口文档。
- 使用 React 和 WebSocket 展示实时协作状态，可选接入模型生成语义说明。

## 快速启动

环境要求：Python 3.12+、Node.js 22+、Git。

首先创建并激活虚拟环境。Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux / macOS：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

随后在仓库根目录执行：

```bash
python -m pip install -e './backend[dev]' -r backend/requirements-interfaces.txt
python -m pip install -e .
npm --prefix frontend ci
python scripts/run_mvp.py --port 8765 --build
```

访问 <http://127.0.0.1:8765/>。启动脚本会在 `.mvp/` 下准备商城示例 Git 仓库和 SQLite 数据库。需要一份全新的演示数据时，使用另一个目录：

```bash
python scripts/run_mvp.py --port 8766 --data-dir .mvp/fresh
```

演示模式提供组长与成员身份切换，方便体验协作流程和权限差异。后端仍会执行权限校验，但此模式不用于认证真实用户身份。

## 配置

将 `mvp.env.example` 复制为 `mvp.env`，根据需要填写配置，修改后重启服务。

| 配置项 | 用途 |
| --- | --- |
| `TEAMCODE_AGENTS` | 服务端配置的 CLI 命令数组和任务传递方式 |
| `TEAMCODE_LLM_BASE_URL` | 可选的 OpenAI-compatible 语义说明服务地址 |
| `TEAMCODE_LLM_API_KEY` | 语义说明服务的密钥 |
| `TEAMCODE_LLM_MODEL` | 生成语义说明使用的模型 |
| `TEAMCODE_LLM_AUTO=1` | 接口扫描后自动更新语义说明 |
| `DATABASE_URL` | 自定义数据库连接 |

默认使用 MockAdapter，不调用外部模型。使用真实 CLI Agent 前，需要单独安装并完成登录；实际调用会使用对应账号的额度。未配置语义说明服务时，AST 接口文档仍可正常生成和更新。

也提供基于 PostgreSQL 的容器部署配置：

```bash
docker compose -f docker-compose.mvp.yml up --build
```

当前开发环境尚未完成容器部署实测。

## 接口文档工具

将环境变量 `TEAMCODE_API_BASE` 设置为后端地址，`TEAMCODE_TOKEN` 设置为成员 token，然后执行：

```bash
teamcode pull-interfaces --project p_demo --output interfaces.md
python -m cli.mcp_server
```

MCP 服务通过标准输入输出通信，提供 `list_interfaces(project_id)` 和 `get_interface(interface_id)`。接口约定见[接口契约](docs/interface_contract.md)，实现细节见[注册中心说明](docs/interface_registry.md)。

## 验证

激活虚拟环境后执行：

```bash
python -m pytest backend/tests -q
npm --prefix frontend run build
python scripts/verify_mvp.py
```

Windows 下需要排除一项创建非法双引号文件名的既有测试：

```bash
python -m pytest backend/tests -q -k 'not test_unusual_filename_is_collected'
```

端到端脚本需要先构建前端，使用 MockAdapter 验证真实的本地 HTTP、WebSocket、Git、pytest、CLI 和 MCP 流程。真实 Agent 验证需手动运行 `scripts/verify_real_agent.py --claude <可执行文件路径>`，会使用账号额度。生成的报告、本地配置、依赖和运行数据不纳入版本控制。

## 目录结构

```text
backend/app/manager_agent/       任务规划与重规划
backend/app/agent_runtime/       会话与 Agent Adapter
backend/app/git_ops/             Git 工作区管理
backend/app/security/            路径权限校验
backend/app/integration/         API 接线、鉴权和运行记录
backend/app/interface_registry/  接口提取、历史和文档
backend/app/realtime/            按权限过滤实时事件
frontend/src/                   React 工作台
cli/                            接口文档 CLI 和 MCP
examples/shop/                  商城示例及测试
scripts/                        本地启动和验证脚本
```
