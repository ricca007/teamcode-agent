"""A/B/C 三部分代码的整合层（C 负责接线）。

- A：Manager Agent 规划 → 持久化为 tasks / task_dependencies / plan_snapshots
- B：Agent Runtime → 会话、日志、变更持久化并推送到 C 的 WebSocket
- C：接口注册中心保持独立，通过 projects.repo_path 扫描同一仓库
"""

from app.integration.api import router

__all__ = ["router"]
