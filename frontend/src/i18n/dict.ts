/**
 * 轻量中英文案字典。
 *
 * 该模块不依赖 React，供组件（经 index.ts 的 hook）与非组件代码
 * （store、api client、format 工具）共用。默认语言为英文，用户切换后
 * 记录在 localStorage("tc_locale")。
 */

export type Locale = "zh" | "en";

export type Params = Record<string, string | number>;

interface Entry {
  zh: string;
  en: string;
}

export const DICT = {
  // 通用
  "common.reload": { zh: "重新加载", en: "Reload" },
  "common.loading": { zh: "加载中…", en: "Loading…" },
  "common.copy": { zh: "复制", en: "Copy" },
  "common.copied": { zh: "已复制", en: "Copied" },
  "common.copiedClipboard": { zh: "已复制到剪贴板", en: "Copied to clipboard" },
  "common.none": { zh: "无", en: "None" },
  "common.yes": { zh: "是", en: "Yes" },
  "common.no": { zh: "否", en: "No" },
  "common.unassigned": { zh: "未分配", en: "Unassigned" },

  // 角色
  "role.leader": { zh: "队长", en: "Leader" },
  "role.member": { zh: "组员", en: "Member" },
  "role.unknown": { zh: "未知角色", en: "Unknown role" },

  // 任务 / 会话状态
  "status.planned": { zh: "待处理", en: "Pending" },
  "status.in_progress": { zh: "进行中", en: "In progress" },
  "status.blocked": { zh: "阻塞", en: "Blocked" },
  "status.completed": { zh: "已完成", en: "Completed" },
  "status.cancelled": { zh: "已取消", en: "Cancelled" },
  "status.pending": { zh: "待启动", en: "Starting" },
  "status.running": { zh: "运行中", en: "Running" },
  "status.paused": { zh: "已暂停", en: "Paused" },
  "status.succeeded": { zh: "已完成", en: "Succeeded" },
  "status.failed": { zh: "失败", en: "Failed" },
  "status.terminated": { zh: "已终止", en: "Terminated" },

  // 接口类型
  "kind.all": { zh: "全部", en: "All" },
  "kind.function": { zh: "函数", en: "Function" },
  "kind.method": { zh: "方法", en: "Method" },
  "kind.class": { zh: "类", en: "Class" },

  // 连接状态
  "conn.open": { zh: "实时连接已建立", en: "Live connection established" },
  "conn.connecting": { zh: "正在建立连接", en: "Connecting" },
  "conn.closed": { zh: "连接中断 · 等待重连", en: "Disconnected · awaiting retry" },
  "conn.live": { zh: "实时推送", en: "Live" },
  "conn.connectingShort": { zh: "连接中", en: "Connecting" },
  "conn.closedShort": { zh: "已断开", en: "Disconnected" },

  // 应用外壳
  "shell.skip": { zh: "跳到主要内容", en: "Skip to main content" },
  "shell.subtitle": { zh: "Agent 协作台", en: "Agent collaboration console" },
  "shell.currentProject": { zh: "当前项目", en: "Current project" },
  "shell.notLoggedIn": { zh: "未登录", en: "Not signed in" },
  "shell.switchTeam": { zh: "切换团队", en: "Switch team" },
  "shell.teamOption": { zh: "{name}（{role}）", en: "{name} ({role})" },
  "shell.logout": { zh: "退出账号", en: "Sign out" },
  "shell.mainNav": { zh: "主导航", en: "Main navigation" },
  "shell.workspace": { zh: "工作区", en: "Workspace" },
  "shell.eventChannel": {
    zh: "事件通道 /ws/projects/{projectId}",
    en: "Event channel /ws/projects/{projectId}",
  },
  "shell.selectAgent": { zh: "选择 Coding Agent", en: "Select a Coding Agent" },
  "shell.notInstalled": { zh: "（未安装）", en: " (not installed)" },
  "shell.refreshData": { zh: "刷新项目数据", en: "Refresh project data" },
  "shell.noTeam": { zh: "未选择团队", en: "No team selected" },

  // 导航
  "nav.dashboard": { zh: "任务看板", en: "Task board" },
  "nav.dashboardHint": { zh: "进度与分配", en: "Progress & assignment" },
  "nav.agents": { zh: "Agent 会话", en: "Agent sessions" },
  "nav.agentsHint": { zh: "状态与日志", en: "Status & logs" },
  "nav.interfaces": { zh: "接口浏览", en: "Interfaces" },
  "nav.interfacesHint": { zh: "签名与版本", en: "Signatures & versions" },
  "nav.changes": { zh: "代码变更", en: "Code changes" },
  "nav.changesHint": { zh: "Diff 与提交", en: "Diffs & commits" },
  "nav.apikeys": { zh: "API Key", en: "API keys" },
  "nav.apikeysHint": { zh: "程序化访问", en: "Programmatic access" },
  "nav.team": { zh: "团队管理", en: "Team" },
  "nav.teamHint": { zh: "大纲与分配", en: "Outline & assignment" },

  // 通用状态块
  "states.loading": { zh: "正在加载数据", en: "Loading data" },
  "states.partialError": { zh: "部分请求没有成功", en: "Some requests failed" },
  "states.retry": { zh: "重试", en: "Retry" },

  // 任务看板
  "dashboard.column.pending": { zh: "待处理", en: "Pending" },
  "dashboard.column.active": { zh: "进行中", en: "In progress" },
  "dashboard.column.attention": { zh: "需处理", en: "Needs attention" },
  "dashboard.column.done": { zh: "已交付", en: "Delivered" },
  "dashboard.noPathLimit": { zh: "未限制路径", en: "No path limit" },
  "dashboard.replan": { zh: "重规划 v{version}", en: "Replanned v{version}" },
  "dashboard.starting": { zh: "启动中", en: "Starting" },
  "dashboard.run": { zh: "运行", en: "Run" },
  "dashboard.depends": { zh: "依赖", en: "Depends on" },
  "dashboard.memberMeta": {
    zh: "{done} / {total} 完成 · {percent}%",
    en: "{done} / {total} done · {percent}%",
  },
  "dashboard.memberProgress": {
    zh: "{name}的任务完成度",
    en: "Task progress for {name}",
  },
  "dashboard.statRunning": { zh: "运行中 {count}", en: "Running {count}" },
  "dashboard.statPending": { zh: "待处理 {count}", en: "Pending {count}" },
  "dashboard.statAttention": { zh: "异常 {count}", en: "Issues {count}" },
  "dashboard.agentUnavailable": {
    zh: "{agent} 当前不可用：请先安装对应 CLI，或在顶部切换一个可用的 Agent",
    en: "{agent} is unavailable. Install its CLI, or switch to an available agent in the header.",
  },
  "dashboard.taskStarted": {
    zh: "任务「{title}」已用 {agent} 启动，日志和状态会自动刷新；可在「Agent 会话」继续追问。",
    en: "Task \"{title}\" started with {agent}. Logs and status refresh automatically; continue in Agent sessions.",
  },
  "dashboard.eyebrow": { zh: "项目进度", en: "Project progress" },
  "dashboard.desc": {
    zh: "任务按负责人拆解，进度以成员为单位汇总，状态随成员会话和代码变更实时更新。本地未配置真实 Coding Agent 时，点击「运行」使用 Mock 适配器模拟执行。",
    en: "Tasks are split by owner and progress is aggregated per member; status updates live with sessions and code changes. Without a real Coding Agent configured, “Run” uses the mock adapter.",
  },
  "dashboard.viewSessions": { zh: "查看 Agent 会话", en: "View agent sessions" },
  "dashboard.tasksDoneTotal": { zh: "/ {total} 个任务完成", en: "/ {total} tasks done" },
  "dashboard.overallProgress": {
    zh: "项目整体任务完成度",
    en: "Overall project task progress",
  },
  "dashboard.running": { zh: "进行中", en: "In progress" },
  "dashboard.pending": { zh: "待处理", en: "Pending" },
  "dashboard.attention": { zh: "需处理", en: "Needs attention" },
  "dashboard.emptyTitle": { zh: "还没有开发任务", en: "No development tasks yet" },
  "dashboard.emptyDesc": {
    zh: "输入项目需求后，Manager Agent 会生成任务、依赖和接口契约。",
    en: "Once requirements are submitted, the Manager Agent generates tasks, dependencies, and interface contracts.",
  },
  "dashboard.memberProgressTitle": { zh: "成员进度", en: "Member progress" },
  "dashboard.groupedByOwner": { zh: "按负责人汇总", en: "Grouped by owner" },
  "dashboard.developmentTasks": { zh: "开发任务", en: "Development tasks" },
  "dashboard.groupBy": { zh: "任务分组方式", en: "Task grouping" },
  "dashboard.byMember": { zh: "按成员", en: "By member" },
  "dashboard.byStatus": { zh: "按状态", en: "By status" },
  "dashboard.noTasks": { zh: "暂无任务", en: "No tasks" },
  "dashboard.columnMeta": {
    zh: "{done}/{total} 完成",
    en: "{done}/{total} done",
  },
  "dashboard.countItems": { zh: "{count} 个", en: "{count}" },

  // Agent 会话
  "agents.actionPaused": { zh: "已暂停", en: "paused" },
  "agents.actionResumed": { zh: "已恢复", en: "resumed" },
  "agents.actionTerminated": { zh: "已终止", en: "terminated" },
  "agents.controlDone": { zh: "{title} {action}", en: "{title} {action}" },
  "agents.messageSent": {
    zh: "消息已发送，Agent 输出会实时出现在日志里",
    en: "Message sent; agent output appears in the log in real time.",
  },
  "agents.eyebrow": { zh: "运行时", en: "Runtime" },
  "agents.desc": {
    zh: "每个任务在独立 Worktree 中运行一个 Coding Agent 会话，日志按会话实时推送。",
    en: "Each task runs a Coding Agent session in its own worktree; logs stream per session.",
  },
  "agents.refresh": { zh: "刷新状态", en: "Refresh status" },
  "agents.loading": { zh: "正在加载会话与日志", en: "Loading sessions and logs" },
  "agents.activeSessions": { zh: "活跃会话", en: "Active sessions" },
  "agents.emptyTitle": { zh: "暂无 Agent 会话", en: "No agent sessions" },
  "agents.emptyDesc": {
    zh: "在任务看板中启动任务后，这里会显示每个会话的工作区与状态。",
    en: "Start a task from the task board and each session’s workspace and status appear here.",
  },
  "agents.recentHint": {
    zh: "仅自动加载最近 {limit} 个任务的会话与日志，更早的按需加载。",
    en: "Only the latest {limit} tasks’ sessions and logs load automatically; earlier ones load on demand.",
  },
  "agents.loadMore": { zh: "加载更早会话", en: "Load earlier sessions" },
  "agents.sessionLogs": { zh: "会话日志", en: "Session logs" },
  "agents.allSessions": { zh: "全部会话", en: "All sessions" },
  "agents.pause": { zh: "暂停", en: "Pause" },
  "agents.resume": { zh: "恢复", en: "Resume" },
  "agents.terminate": { zh: "终止", en: "Terminate" },
  "agents.autoScroll": { zh: "自动滚动", en: "Auto-scroll" },
  "agents.noLogsTitle": { zh: "这个会话还没有日志", en: "No logs for this session yet" },
  "agents.noLogsDesc": {
    zh: "Agent 启动后，stdout 与 stderr 会按时间顺序显示在这里。",
    en: "Once the agent starts, stdout and stderr appear here in chronological order.",
  },
  "agents.liveLogs": { zh: "Agent 实时日志", en: "Agent live logs" },
  "agents.chatBusy": {
    zh: "Agent 正在执行，完成后可继续对话",
    en: "The agent is running; you can chat again when it finishes",
  },
  "agents.chatPlaceholder": {
    zh: "继续让 Agent 修改代码，例如：把 create 改成异步",
    en: "Ask the agent to keep changing code, e.g. make create async",
  },
  "agents.chatAria": { zh: "发送给 Agent 的消息", en: "Message to the agent" },
  "agents.sending": { zh: "发送中", en: "Sending" },
  "agents.send": { zh: "发送", en: "Send" },

  // 接口浏览
  "interfaces.rescanned": { zh: "接口已重新扫描", en: "Interfaces rescanned" },
  "interfaces.copyFailed": {
    zh: "复制失败，请手动选择文本",
    en: "Copy failed; select the text manually",
  },
  "interfaces.eyebrow": { zh: "接口注册中心", en: "Interface registry" },
  "interfaces.desc": {
    zh: "AST 自动提取的函数签名、参数与版本。每位成员的 Coding Agent 通过同一份文档获取接口契约。",
    en: "Function signatures, parameters, and versions extracted by AST. Every member’s Coding Agent gets the same interface contract from one document.",
  },
  "interfaces.scanning": { zh: "扫描中", en: "Scanning" },
  "interfaces.rescan": { zh: "重新扫描", en: "Rescan" },
  "interfaces.download": { zh: "下载 Markdown", en: "Download Markdown" },
  "interfaces.loading": {
    zh: "正在加载接口注册中心",
    en: "Loading interface registry",
  },
  "interfaces.search": { zh: "搜索接口", en: "Search interfaces" },
  "interfaces.searchPlaceholder": {
    zh: "搜索名称、模块或路径",
    en: "Search name, module, or path",
  },
  "interfaces.kindFilter": { zh: "接口类型筛选", en: "Filter by interface type" },
  "interfaces.list": { zh: "接口列表", en: "Interfaces" },
  "interfaces.emptyTitle": {
    zh: "接口注册中心暂无数据",
    en: "No interfaces registered",
  },
  "interfaces.mismatchTitle": { zh: "没有匹配的接口", en: "No matching interfaces" },
  "interfaces.emptyDesc": {
    zh: "运行 teamcode pull-interfaces，或点击重新扫描。",
    en: "Run teamcode pull-interfaces, or click Rescan.",
  },
  "interfaces.mismatchDesc": {
    zh: "换一个关键词，或把类型筛选切回全部。",
    en: "Try another keyword, or switch the type filter back to All.",
  },
  "interfaces.copySignatureAria": {
    zh: "复制函数签名",
    en: "Copy function signature",
  },
  "interfaces.copySignature": { zh: "复制签名", en: "Copy signature" },
  "interfaces.noDocstring": {
    zh: "这个接口还没有 docstring。",
    en: "This interface has no docstring yet.",
  },
  "interfaces.params": { zh: "参数", en: "Parameters" },
  "interfaces.noParams": { zh: "无参数", en: "No parameters" },
  "interfaces.param": { zh: "参数", en: "Param" },
  "interfaces.type": { zh: "类型", en: "Type" },
  "interfaces.default": { zh: "默认值", en: "Default" },
  "interfaces.notAnnotated": { zh: "未标注", en: "Unannotated" },
  "interfaces.metadata": { zh: "元数据", en: "Metadata" },
  "interfaces.module": { zh: "模块", en: "Module" },
  "interfaces.location": { zh: "位置", en: "Location" },
  "interfaces.returns": { zh: "返回类型", en: "Returns" },
  "interfaces.commit": { zh: "提交", en: "Commit" },
  "interfaces.decorators": { zh: "装饰器", en: "Decorators" },
  "interfaces.async": { zh: "异步", en: "Async" },
  "interfaces.dependencies": { zh: "依赖接口", en: "Dependencies" },
  "interfaces.markdownCopied": { zh: "已复制 Markdown", en: "Markdown copied" },
  "interfaces.copyMarkdown": { zh: "复制 Markdown", en: "Copy Markdown" },
  "interfaces.selectTitle": { zh: "选择一个接口", en: "Select an interface" },
  "interfaces.selectDesc": {
    zh: "左侧列表展示由 AST 提取的函数、方法与类签名。",
    en: "The list on the left shows function, method, and class signatures extracted by AST.",
  },

  // 代码变更
  "changes.diffAria": { zh: "{task} 的代码差异", en: "Code diff for {task}" },
  "changes.collapse": { zh: "收起 diff", en: "Collapse diff" },
  "changes.expand": { zh: "展开全部 {lines} 行", en: "Show all {lines} lines" },
  "changes.eyebrow": { zh: "协作记录", en: "Collaboration log" },
  "changes.desc": {
    zh: "来自各任务 Worktree 的 Git diff 与提交记录。共 {changes} 次变更，{files} 个文件。",
    en: "Git diffs and commits from each task worktree. {changes} changes across {files} files.",
  },
  "changes.refresh": { zh: "刷新变更", en: "Refresh changes" },
  "changes.loading": { zh: "正在加载代码变更", en: "Loading code changes" },
  "changes.emptyTitle": { zh: "还没有代码变更", en: "No code changes yet" },
  "changes.emptyDesc": {
    zh: "Coding Agent 写入文件并提交后，diff 与提交哈希会出现在这里。",
    en: "Once a Coding Agent writes files and commits, diffs and commit hashes appear here.",
  },

  // API Key
  "apikeys.onlyOnce": {
    zh: "API Key 只显示一次，请立即复制保存",
    en: "The API key is shown only once; copy and save it now",
  },
  "apikeys.revokedNotice": { zh: "已撤销 {name}", en: "Revoked {name}" },
  "apikeys.copyFailed": {
    zh: "复制失败，请手动选择",
    en: "Copy failed; select it manually",
  },
  "apikeys.eyebrow": { zh: "程序化访问", en: "Programmatic access" },
  "apikeys.desc": {
    zh: "给 Coding Agent、CLI 或外部脚本使用的长期凭据。Key 继承你的账号和项目角色，可随时撤销。",
    en: "Long-lived credentials for Coding Agents, the CLI, or external scripts. Keys inherit your account and project role and can be revoked anytime.",
  },
  "apikeys.newKey": { zh: "新建 Key", en: "New key" },
  "apikeys.purpose": { zh: "用途名称", en: "Purpose" },
  "apikeys.purposePlaceholder": {
    zh: "例如 claude-code-lin",
    en: "e.g. claude-code-lin",
  },
  "apikeys.scopeOnly": { zh: "仅限当前项目 {project}", en: "Only this project ({project})" },
  "apikeys.creating": { zh: "创建中", en: "Creating" },
  "apikeys.create": { zh: "生成 API Key", en: "Create API key" },
  "apikeys.copyNow": {
    zh: "请立即复制，关闭后无法再次查看：",
    en: "Copy it now; you can’t view it again after closing:",
  },
  "apikeys.existing": { zh: "已有 Key", en: "Existing keys" },
  "apikeys.empty": { zh: "还没有 API Key。", en: "No API keys yet." },
  "apikeys.revokedSuffix": { zh: "（已撤销）", en: " (revoked)" },
  "apikeys.allProjects": { zh: "全部项目", en: "All projects" },
  "apikeys.revoke": { zh: "撤销", en: "Revoke" },

  // 团队管理
  "team.outlineLoaded": { zh: "已载入大纲：{file}", en: "Outline loaded: {file}" },
  "team.generated": {
    zh: "已根据大纲生成任务，可在任务看板分配或直接运行",
    en: "Tasks generated from the outline. Assign or run them from the task board.",
  },
  "team.approved": {
    zh: "已批准 {name} 加入团队",
    en: "Approved {name} to join the team",
  },
  "team.rejected": { zh: "已拒绝 {name}", en: "Rejected {name}" },
  "team.reassigned": { zh: "任务已重新分配", en: "Task reassigned" },
  "team.merged": {
    zh: "已合并 {task}；接口注册表已刷新",
    en: "Merged {task}; interface registry refreshed",
  },
  "team.mergedWithCount": {
    zh: "已合并 {task}；接口注册表已刷新（当前 {total} 个接口）",
    en: "Merged {task}; interface registry refreshed ({total} interfaces)",
  },
  "team.eyebrow": { zh: "队长工作台", en: "Leader workspace" },
  "team.title": {
    zh: "大纲、成员与任务分配",
    en: "Outline, members, and task assignment",
  },
  "team.desc": {
    zh: "粘贴或上传 Markdown 大纲生成任务；批准成员加入后，把 A/B/C 角色任务分配给具体成员。",
    en: "Paste or upload a Markdown outline to generate tasks; after approving members, assign A/B/C role tasks to specific people.",
  },
  "team.outline": { zh: "项目大纲", en: "Project outline" },
  "team.pasteOutline": { zh: "粘贴 Markdown 大纲", en: "Paste a Markdown outline" },
  "team.outlinePlaceholder": {
    zh: "# 在线商城\n- 用户管理\n- 商品管理\n- 订单管理",
    en: "# Online Store\n- User management\n- Product management\n- Order management",
  },
  "team.uploadFile": { zh: "上传 .md 文件", en: "Upload a .md file" },
  "team.roles": {
    zh: "占位角色（逗号分隔）",
    en: "Placeholder roles (comma separated)",
  },
  "team.generating": { zh: "生成中", en: "Generating" },
  "team.generate": { zh: "生成任务", en: "Generate tasks" },
  "team.joinRequests": { zh: "加入申请", en: "Join requests" },
  "team.noRequests": { zh: "暂无待审批申请。", en: "No pending requests." },
  "team.areasPlaceholder": {
    zh: "负责模块，如 user,order",
    en: "Assigned modules, e.g. user,order",
  },
  "team.approve": { zh: "批准", en: "Approve" },
  "team.reject": { zh: "拒绝", en: "Reject" },
  "team.members": { zh: "成员与任务分配", en: "Members and assignments" },
  "team.noTasks": {
    zh: "还没有任务，先用大纲生成。",
    en: "No tasks yet. Generate some from an outline first.",
  },
  "team.current": { zh: "当前：{owner}", en: "Current: {owner}" },
  "team.merge": { zh: "合并", en: "Merge" },

  // 登录 / 团队初始化
  "auth.restoring": { zh: "正在恢复登录状态", en: "Restoring your session" },
  "auth.pendingEyebrow": { zh: "等待队长批准", en: "Awaiting leader approval" },
  "auth.pendingTitle": { zh: "已申请加入团队", en: "Join request submitted" },
  "auth.teamId": { zh: "团队 ID", en: "Team ID" },
  "auth.autoEnter": {
    zh: "队长批准后会自动进入，不需要重新登录。",
    en: "You’ll enter automatically once the leader approves; no need to sign in again.",
  },
  "auth.back": { zh: "返回", en: "Back" },
  "auth.loggedIn": { zh: "已登录", en: "Signed in" },
  "auth.setupTitle": { zh: "创建或加入团队", en: "Create or join a team" },
  "auth.teamMode": { zh: "团队方式", en: "Team mode" },
  "auth.createTeam": { zh: "创建团队", en: "Create team" },
  "auth.joinTeam": { zh: "加入团队", en: "Join team" },
  "auth.teamName": { zh: "团队名称", en: "Team name" },
  "auth.repoPath": {
    zh: "代码仓库路径（必须是 Git 仓库）",
    en: "Repository path (must be a Git repo)",
  },
  "auth.creating": { zh: "创建中", en: "Creating" },
  "auth.createBecomeLeader": {
    zh: "创建并成为队长",
    en: "Create and become leader",
  },
  "auth.applying": { zh: "申请中", en: "Applying" },
  "auth.applyJoin": { zh: "申请加入", en: "Request to join" },
  "auth.loginOrRegister": { zh: "登录或注册", en: "Sign in or register" },
  "auth.hint": {
    zh: "一个账号可以加入多个团队；在不同团队里可以是队长或组员，也可同时在多个项目中拥有任务。",
    en: "One account can join multiple teams, be a leader in one and a member in another, and hold tasks across projects at the same time.",
  },
  "auth.loginMode": { zh: "登录方式", en: "Sign-in method" },
  "auth.login": { zh: "登录", en: "Sign in" },
  "auth.register": { zh: "注册", en: "Register" },
  "auth.email": { zh: "邮箱", en: "Email" },
  "auth.password": { zh: "密码", en: "Password" },
  "auth.loggingIn": { zh: "登录中", en: "Signing in" },
  "auth.nickname": { zh: "昵称", en: "Display name" },
  "auth.passwordMin": {
    zh: "密码（至少 6 位）",
    en: "Password (at least 6 characters)",
  },
  "auth.registering": { zh: "注册中", en: "Registering" },
  "auth.teamIdPlaceholder": { zh: "例如 p_demo", en: "e.g. p_demo" },

  // 错误边界
  "errors.pageTitle": { zh: "页面渲染出错", en: "Page failed to render" },
  "errors.pageDesc": {
    zh: "{message}。错误详情已写入浏览器控制台。",
    en: "{message}. Details were written to the browser console.",
  },
  "errors.unknown": { zh: "未知错误", en: "Unknown error" },

  // 格式化
  "format.timeUnknown": { zh: "时间未知", en: "Unknown time" },
  "format.uncommitted": { zh: "工作区未提交", en: "Uncommitted workspace" },
  "format.mdType": { zh: "类型", en: "Type" },
  "format.mdModule": { zh: "模块", en: "Module" },
  "format.mdFile": { zh: "文件", en: "File" },
  "format.mdVersion": { zh: "版本", en: "Version" },
  "format.mdCommit": { zh: "提交", en: "Commit" },

  // store
  "store.partialModules": {
    zh: "部分模块可能尚未上线。",
    en: "Some modules may not be live yet.",
  },
  "store.loadFailed": { zh: "加载项目数据失败", en: "Failed to load project data" },

  // api client
  "api.networkError": {
    zh: "无法连接后端 {base}",
    en: "Cannot reach backend {base}",
  },
  "api.sameOrigin": { zh: "（同源）", en: "(same origin)" },
  "api.httpError": {
    zh: "请求失败（HTTP {status}）",
    en: "Request failed (HTTP {status})",
  },
  "api.sessionUnavailable": {
    zh: "任务 {id} 会话不可用：{message}",
    en: "Task {id} session unavailable: {message}",
  },
  "api.logsUnavailable": {
    zh: "任务 {id} 日志不可用：{message}",
    en: "Task {id} logs unavailable: {message}",
  },
  "api.changesUnavailable": {
    zh: "任务 {id} 变更不可用：{message}",
    en: "Task {id} changes unavailable: {message}",
  },
  "api.tasksUnavailable": {
    zh: "任务接口不可用：{message}",
    en: "Tasks API unavailable: {message}",
  },
  "api.interfacesUnavailable": {
    zh: "接口注册中心不可用：{message}",
    en: "Interface registry unavailable: {message}",
  },
  "api.unknown": { zh: "未知错误", en: "Unknown error" },
} as const satisfies Record<string, Entry>;

export type TKey = keyof typeof DICT;

const LOCALE_KEY = "tc_locale";
const DEFAULT_LOCALE: Locale = "en";

function readStoredLocale(): Locale {
  try {
    const saved =
      typeof window !== "undefined"
        ? window.localStorage.getItem(LOCALE_KEY)
        : null;
    if (saved === "zh" || saved === "en") {
      return saved;
    }
  } catch {
    // localStorage 不可用时回退默认语言
  }
  return DEFAULT_LOCALE;
}

let currentLocale: Locale = readStoredLocale();
const listeners = new Set<() => void>();

function syncDocumentLang(): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = currentLocale === "zh" ? "zh-CN" : "en";
  }
}

syncDocumentLang();

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocale(locale: Locale): void {
  if (locale === currentLocale) {
    return;
  }
  currentLocale = locale;
  try {
    window.localStorage.setItem(LOCALE_KEY, locale);
  } catch {
    // 忽略持久化失败，本次会话内仍然生效
  }
  syncDocumentLang();
  listeners.forEach((listener) => listener());
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function translate(
  key: TKey,
  params?: Params,
  locale: Locale = currentLocale,
): string {
  let text: string = DICT[key][locale];
  if (params) {
    text = text.replace(/\{(\w+)\}/g, (match, name: string) =>
      params[name] === undefined ? match : String(params[name]),
    );
  }
  return text;
}

export type { Entry };
