# Interface Registry 集成说明（C 负责）

> 本文档说明 C 的接口注册中心如何适配 A/B 已落地的 async SQLAlchemy 骨架。
> 公共契约仍以 `docs/interface_contract.md` 为准；本文只记录 C 的新增与取舍。

## 1. 适配原则

- **不改 A/B 的业务代码**：`manager_agent/`、`agent_runtime/`、`git_ops/`、
  `security/`、`app/models/` 中属于 A/B 的模型均未修改。
- **复用公共模型**：接口主表继续使用 A 的
  `app.models.interface.InterfaceContract`，状态存 `in_progress` 等小写值。
- **异步一致**：C 的 service 全部使用 `AsyncSession`，与 A 的
  `app/db.py` 共用同一个异步引擎。
- **只做最小接线**：在 `app/main.py` 增加两行 `include_router`，注册 C 的
  REST 与 WebSocket 路由；`/health` 的返回保持原样（有测试锁定）。

## 2. 数据模型

公共表 `interface_contracts` 保持不变。C 在自己的 metadata 下新增两张表：

| 表 | 作用 |
| --- | --- |
| `interface_registry_state` | 与主表一对一：内容哈希、软删除标记、行号、装饰器、是否 async |
| `interface_versions` | 每次新增 / 更新 / 删除追加一条历史快照 |

为什么单独建 metadata：

- A 的 `test_models.py` 对 `Base.metadata.tables` 做了精确断言，直接往公共
  `Base` 加表会破坏他们的测试；
- 接口表按分工属于 C，但字段变更需要三人确认。先用独立表落地，等 A 确认后
  可以平滑合并进公共契约。

迁移文件：`backend/alembic/versions/8b7f1c2d4a90_add_interface_registry_tables.py`。
单测 / CLI 离线模式也会通过 `ensure_registry_tables()` 懒建表，不依赖迁移。

## 3. REST 与实时事件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/projects/{id}/interfaces?format=json\|markdown` | 列表 / 文档 |
| GET | `/api/interfaces/{interface_id}` | 单个接口 |
| POST | `/api/projects/{id}/interfaces/refresh` | 手动重扫 |
| GET | `/health/interfaces` | 监听降级状态（C 独立入口） |
| WS | `/ws/projects/{id}` | `interface.updated` 事件 |

事件格式与公共契约一致；payload 包含 `added / updated / deleted /
scanned_files / total_interfaces`。

## 4. CLI 与 MCP

```bash
# 在线：走 REST
teamcode pull-interfaces --project p_001 --output context/interfaces.md

# 离线：直接读数据库（自动从 PostgreSQL 降级到 SQLite，并打印降级原因）
teamcode pull-interfaces --project p_001 --offline \
  --db-url sqlite+aiosqlite:///./teamcode.db
```

MCP server：

```bash
python -m cli.mcp_server --db-url sqlite+aiosqlite:///./teamcode.db
```

提供 `list_interfaces` 与 `get_interface` 两个工具，复用同一个 service。

## 5. 前端

- React + TypeScript + Vite，只保留实时模式（已删除 mock / 演示数据）；
- 开发时 Vite 把 `/api`、`/ws` 代理到 `http://127.0.0.1:8000`，避免 CORS；
- 侧栏可切换项目 ID，默认读取 `VITE_PROJECT_ID`；
- 接口浏览页支持搜索、类型筛选、复制签名 / Markdown、手动重扫、下载文档。

## 6. 验证方式

一键端到端验证（临时 SQLite + 真实 uvicorn，不改仓库数据）：

```bash
.venv/bin/python scripts/verify_interfaces.py
```

覆盖 17 项检查：迁移、`/health` 契约、扫描、JSON / Markdown、详情、404、
版本递增、WebSocket（手动刷新 + watchdog 自动监听）、CLI 在线 / 离线、MCP、
软删除。

## 7. 手动演示（本地 SQLite）

```bash
# 1) 准备 /tmp 下的演示仓库与数据库（会立即扫描 11 个接口）
.venv/bin/python scripts/seed_demo_project.py --reset

# 2) 启动后端（使用脚本打印的 DATABASE_URL）
cd backend
DATABASE_URL="sqlite+aiosqlite:////tmp/teamcode-demo.db" \
  ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 3) 另开终端启动前端
cd frontend && npm run dev
# 浏览器打开 http://localhost:5173，侧栏输入项目 ID：p_demo
```

手动修改 `/tmp/teamcode-demo-repo/users.py` 后：
- 装了 watchdog：约 0.5–1 秒内接口浏览页自动刷新版本；
- 没装 watchdog：点击「重新扫描」即可，`/health/interfaces` 会显示降级原因。

## 8. 评测方式

```bash
.venv/bin/python experiments/eval_interfaces.py
# 也可以输出 JSON 供脚本消费
.venv/bin/python experiments/eval_interfaces.py --format json \
  --output experiments/reports/interfaces.json
```

指标：

- 提取字段级准确率（`expected.json` 逐字段比对）；
- 全量 / 增量扫描耗时；
- 变更到实时事件的端到端延迟（含防抖）；
- 版本递增、历史快照、软删除、Markdown 一致性。

报告输出到 `experiments/reports/interfaces.md`。

## 8. 错误兜底与日志

原则：**可预期错误给用户明确提示；未预期错误记录完整堆栈；能降级的绝不阻断主流程。**

| 层 | 兜底措施 | 日志 |
| --- | --- | --- |
| 扫描 | `asyncio.Lock` 串行；`IntegrityError` 自动回滚并重试 1 次；失败回滚 | `app.interface_registry.service`：扫描开始/完成耗时、并发重试、失败堆栈 |
| 建表 | Alembic + 懒建表双保险；按事件循环加锁防并发重复建表 | 建表失败 `logger.exception`，成功 `INFO` |
| 文件监听 | watchdog 缺失/启动失败 → `degraded`，手动刷新仍可用；监听线程异常自兜底；事件发布失败不影响已落库结果 | `app.interface_registry.watcher`：启动、降级原因、扫描失败、发布失败 |
| 实时推送 | 无事件循环时丢弃事件不抛错；死连接自动移除；调度异常只记录 | `app.realtime.*`：连接、断开、推送失败 |
| REST | 可预期错误返回 `{code,message,detail}`；未预期异常返回结构化 500，不泄露 traceback；事件/监听失败只降级 | `app.interface_registry.api`：刷新开始/结束、404/422 原因、500 堆栈 |
| CLI | 数据库不可用自动回退 SQLite；SQLite 自身失败不假装成功；写文件失败有提示；退出码 0/2 | `teamcode.cli`：在线/离线数据源、降级原因、错误堆栈，全部写 stderr |
| MCP | 工具异常转 JSON-RPC 错误；stdout 只输出协议消息；数据库降级提示走 stderr | `teamcode.mcp`：工具失败堆栈、未知工具/方法 |
| 前端 | 页面级 `ErrorBoundary` 防白屏；WS 指数退避重连并**重连后自动全量刷新**；请求令牌丢弃过期响应；各模块独立加载，单个接口失败不拖垮页面 | 浏览器控制台：渲染错误、未处理 Promise、未捕获异常、WS 异常 |

后端日志默认输出到 stderr（`configure_logging()` 会把
`app.interface_registry` / `app.realtime` 调到 INFO）。pytest 环境不会覆盖
已有的 logging handler。

## 9. 已知限制

- 进程内扫描锁按「项目 + 事件循环」隔离；多进程部署时依赖数据库主键兜底，
  极端并发下可能需要 advisory lock。
- 每个后端进程都会启动 watchdog，多 worker 会重复推送；演示环境默认单进程。
- 文件移动按「旧接口删除 + 新接口新增」处理，版本不延续。
- `interface_versions` 目前没有清理策略，课程规模可接受。
