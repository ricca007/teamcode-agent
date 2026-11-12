import { useCallback, useEffect, useState } from "react";
import { download, request, save, socketUrl } from "./api";
import * as demo from "./demo";
import { labels, signature, type Change, type Documentation, type Interface, type Log, type Member,
  type Plan, type Session, type Task, type TestResult, type Version } from "./types";

const offline = new URLSearchParams(location.search).get("demo") === "1";
const credentials = new URLSearchParams(location.hash.slice(1));
export default function App() {
  const [project, setProject] = useState(credentials.get("project") ?? sessionStorage.getItem("mvp_project") ?? "p_demo");
  const [token, setToken] = useState(credentials.get("token") ?? sessionStorage.getItem("mvp_token") ?? "");
  const [identities, setIdentities] = useState<Member[]>([]);
  const [me, setMe] = useState<Member | null>(offline ? demo.members[0] : null);
  const [members, setMembers] = useState<Member[]>(offline ? demo.members : []);
  const [tasks, setTasks] = useState<Task[]>(offline ? demo.tasks : []);
  const [interfaces, setInterfaces] = useState<Interface[]>(offline ? demo.interfaces : []);
  const [plan, setPlan] = useState<Plan | null>(offline ? demo.plan : null);
  const [taskId, setTaskId] = useState("");
  const [interfaceId, setInterfaceId] = useState("");
  const [session, setSession] = useState<Session>({ status: "pending" });
  const [logs, setLogs] = useState<Log[]>(offline ? demo.logs : []);
  const [changes, setChanges] = useState<Change[]>(offline ? demo.changes : []);
  const [tests, setTests] = useState<TestResult>(offline ? demo.tests : { status: "not_run" });
  const [versions, setVersions] = useState<Version[]>([]);
  const [documentation, setDocumentation] = useState<Documentation>({ configured: false, stale: false, document: null });
  const [agents, setAgents] = useState(["mock"]);
  const [agent, setAgent] = useState("mock");
  const [requirement, setRequirement] = useState("在线商城：用户管理、商品管理、订单管理");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("logs");
  const [connection, setConnection] = useState(offline ? "离线示例" : "正在连接");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const task = tasks.find(t => t.task_id === taskId) ?? tasks[0];
  const filtered = interfaces.filter(i => `${i.name} ${i.module} ${i.docstring}`.toLowerCase().includes(query.toLowerCase()));
  const info = filtered.find(i => i.interface_id === interfaceId) ?? filtered[0];
  const p = `/api/projects/${encodeURIComponent(project)}`;
  const t = task ? `/api/tasks/${encodeURIComponent(task.task_id)}` : "";
  const leader = me?.role === "leader";
  const canExecute = !offline && !!task && (leader || me?.user_id === task.owner_id);

  useEffect(() => {
    if (offline) return;
    void request<{ project_id: string; members: Member[] }>("/api/demo", "").then(data => {
      setIdentities(data.members);
      if (!credentials.get("token") && !sessionStorage.getItem("mvp_token")) {
        setProject(data.project_id); setToken(data.members[0].token ?? "");
      }
    }).catch(() => setNotice("请在连接设置中填入项目 ID 和成员 token。"));
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (offline || !token) return;
    const [taskData, interfaceData, memberData, planData, docData, actor, agentData] = await Promise.all([
      request<{ tasks: Task[] }>(p + "/tasks", token, undefined, signal),
      request<{ interfaces: Interface[] }>(p + "/interfaces", token, undefined, signal),
      request<{ members: Member[] }>(p + "/members", token, undefined, signal),
      request<Plan>(p + "/plan", token, undefined, signal).catch(() => null),
      request<Documentation>(p + "/documentation", token, undefined, signal),
      request<Member>("/api/me", token, undefined, signal),
      request<{ agents: { name: string }[] }>("/api/agents", token, undefined, signal),
    ]);
    if (signal?.aborted) return;
    setTasks(taskData.tasks); setInterfaces(interfaceData.interfaces); setMembers(memberData.members);
    setPlan(planData); setDocumentation(docData); setMe(actor); setAgents(agentData.agents.map(a => a.name));
  }, [p, token]);

  useEffect(() => {
    if (offline) return;
    const controller = new AbortController();
    setTasks([]); setInterfaces([]); setLogs([]); setChanges([]); setMe(null); setError("");
    setTaskId(""); setInterfaceId(""); setTests({ status: "not_run" });
    sessionStorage.setItem("mvp_token", token);
    sessionStorage.setItem("mvp_project", project);
    void load(controller.signal).catch(e => { if (!controller.signal.aborted) setError(String(e.message)); });
    return () => controller.abort();
  }, [load, token]);

  useEffect(() => {
    if (offline || !token) return;
    let socket: WebSocket | undefined, retry: ReturnType<typeof setTimeout>, stopped = false;
    const controller = new AbortController();
    const refresh = () => void load(controller.signal).catch(() => {});
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(socketUrl(`/ws/projects/${encodeURIComponent(project)}`, token));
      socket.onopen = () => { setConnection("实时连接已建立"); refresh(); };
      socket.onmessage = e => {
        try { const event = JSON.parse(e.data); if (event.type !== "pong") refresh(); } catch { /* ignore */ }
      };
      socket.onclose = () => { if (!stopped) { setConnection("连接中断 · 自动重连"); retry = setTimeout(connect, 2000); } };
      socket.onerror = () => socket?.close();
    };
    connect();
    // WS 通知更新；少量轮询补齐会话/测试等持久化结果，也覆盖断线期间的事件。
    const poll = setInterval(refresh, 4000);
    return () => { stopped = true; controller.abort(); clearTimeout(retry); clearInterval(poll); socket?.close(); };
  }, [project, token, load]);

  useEffect(() => {
    if (offline || !task || !token) return;
    const controller = new AbortController();
    setSession({ status: "pending" }); setLogs([]); setChanges([]); setTests({ status: "not_run" });
    if (!canExecute) return () => controller.abort();
    const refresh = async () => {
      try {
        const [s, l, c, test] = await Promise.all([
          request<Session>(t + "/status", token, undefined, controller.signal),
          request<{ logs: Log[] }>(t + "/logs", token, undefined, controller.signal),
          request<{ changes: Change[] }>(t + "/changes", token, undefined, controller.signal),
          request<TestResult>(t + "/tests", token, undefined, controller.signal),
        ]);
        if (!controller.signal.aborted) { setSession(s); setLogs(l.logs); setChanges(c.changes); setTests(test); }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 1500);
    return () => { controller.abort(); clearInterval(timer); };
  }, [t, token, canExecute]);

  useEffect(() => {
    if (offline) {
      setVersions(info ? [{ version: 2, snapshot: info, created_at: "离线示例" }] : []); return;
    }
    if (!info || !token) { setVersions([]); return; }
    const controller = new AbortController();
    void request<{ versions: Version[] }>(`/api/interfaces/${info.interface_id}/versions`, token,
      undefined, controller.signal).then(data => { if (!controller.signal.aborted) setVersions(data.versions); })
      .catch(() => {});
    return () => controller.abort();
  }, [info?.interface_id, info?.version, token]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); await load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const post = (path: string, body: unknown = {}) => act(() => request(path, token, body));
  async function invite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await act(async () => {
      const member = await request<Member>(p + "/members", token, { name: data.get("name") });
      const hash = new URLSearchParams({ project, token: member.token ?? "" });
      setNotice(`成员已加入。将此链接交给该成员：${location.origin}/#${hash}`);
    });
  }
  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const result = await request<{ id: string; token: string }>("/api/projects", token,
        { name: data.get("name"), repo_path: data.get("repo_path") });
      setProject(result.id); setToken(result.token);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return <main>
    <header className="top"><div><strong className="brand">TeamCode<span> / MVP</span></strong>
      <p>小组开发，从需求到接口共享。</p></div><div className="connection"><i />{connection}</div>
      <a href={offline ? "/" : "/?demo=1"}>{offline ? "连接后端" : "离线演示"}</a>
      {!offline && <select aria-label="课堂身份" value={identities.find(m => m.token === token)?.user_id ?? "external"}
        onChange={e => { const m = identities.find(i => i.user_id === e.target.value); if (m) { setProject("p_demo"); setToken(m.token!); } }}>
        <option value="external">自定义成员</option>{identities.map(m => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
      </select>}
    </header>
    {offline && <p className="banner">离线展示：任务、日志、Diff 和测试结果均为模拟数据，不用于实验统计。</p>}
    <details className="settings"><summary>连接与项目设置 <small>{project} · {me?.name ?? "未连接"}</small></summary>
      <form className="form-row" key={project + token.slice(-6)} onSubmit={e => {
        e.preventDefault(); const data = new FormData(e.currentTarget);
        setProject(String(data.get("project"))); setToken(String(data.get("token")));
      }}><label>项目 ID<input name="project" defaultValue={project} disabled={offline} /></label>
        <label>成员 token<input name="token" type="password" defaultValue={token} disabled={offline} autoComplete="off" /></label>
        <button disabled={offline}>连接项目</button></form>
      {leader && !offline && <div className="form-row"><form onSubmit={invite}><input name="name" placeholder="新成员姓名" aria-label="新成员姓名" required /><button disabled={busy}>邀请成员</button></form>
        <form onSubmit={create}><input name="name" placeholder="新项目名称" aria-label="新项目名称" required /><input name="repo_path" placeholder="已有 Git 仓库绝对路径" aria-label="仓库路径" required /><button disabled={busy}>创建项目</button></form></div>}
    </details>
    {error && <p className="banner error" role="alert">{error}</p>}
    {notice && <p className="banner" role="status">{notice}</p>}
    <section className="metrics" aria-label="项目进度">
      <div><strong>{tasks.filter(t => t.status === "completed").length}<small> / {tasks.length}</small></strong><span>任务已完成</span></div>
      <div><strong>{interfaces.length}</strong><span>已发现接口</span></div>
      <div><strong>{members.length}</strong><span>协作成员</span></div>
      <div><strong>v{plan?.version ?? "—"}</strong><span>当前计划</span></div>
    </section>
    <section className="panel planning"><div className="section-head"><h2>01 / 需求与规划</h2><span>A · Manager Agent</span></div>
      <textarea aria-label="项目需求" value={requirement} onChange={e => setRequirement(e.target.value)} rows={2} disabled={offline || !leader} />
      <div className="toolbar"><button className="primary" disabled={busy || offline || !leader || !!plan} onClick={() => void post(p + "/requirements", { requirements: requirement, mode: "plan" })}>生成计划</button>
        <button disabled={busy || offline || !leader || !plan} onClick={() => void post(p + "/requirements", { requirements: requirement, mode: "replan" })}>更新需求并重规划</button>
        <button className="text" disabled={offline || !leader} onClick={() => setRequirement("在线商城：用户管理、商品管理、订单管理，新增优惠券功能，订单支持优惠券抵扣")}>填入优惠券变更示例</button>
      </div>
      {plan?.diff && <p className="impact">新增 {plan.diff.added_tasks.length} 项，修改 {plan.diff.updated_tasks.length} 项，保留 {plan.diff.unchanged_tasks.length} 项。{plan.diff.impact_notes.join("；")}</p>}
    </section>
    <div className="work-grid">
      <section className="panel"><div className="section-head"><h2>02 / 任务看板</h2><span>{tasks.length} TASKS</span></div>
        <div className="task-list">{tasks.map(item => <button className={`task ${item.task_id === task?.task_id ? "selected" : ""}`} key={item.task_id} onClick={() => setTaskId(item.task_id)}>
          <span className={`pill ${item.status}`}>{labels[item.status]}</span><strong>{item.title}</strong>
          <small>{members.find(m => m.user_id === item.owner_id)?.name ?? item.owner_id}</small>
        </button>)}{!tasks.length && <p className="empty">生成计划后，成员任务会出现在这里。</p>}</div>
      </section>
      <section className="panel runtime"><div className="section-head"><h2>03 / Agent 工作区</h2><span>B · Coding Agent</span></div>
        {task ? <><h3>{task.title}</h3><p className="muted">{task.description}</p>
          <div className="task-meta"><span>允许修改 <code>{task.allowed_paths.join(", ")}</code></span>
            <span>依赖 {task.depends_on.length ? task.depends_on.map(id => tasks.find(t => t.task_id === id)?.title ?? id).join("、") : "无"}</span></div>
          <div className="toolbar"><select aria-label="Coding Agent" value={agent} onChange={e => setAgent(e.target.value)} disabled={offline}>
            {agents.map(a => <option key={a} value={a}>{a === "mock" ? "Mock · 联调演示" : a}</option>)}</select>
            <button className="primary" disabled={busy || !canExecute || task.status === "in_progress"} onClick={() => void post(t + "/run", { agent_name: agent })}>运行</button>
            {(["pause", "resume", "terminate"] as const).map((action, i) => <button key={action}
              disabled={busy || !canExecute || task.status !== "in_progress" ||
                (action === "pause" ? session.status !== "running" : action === "resume" ? session.status !== "paused" : !["running", "paused", "pending"].includes(session.status))}
              onClick={() => void post(t + "/" + action)}>{["暂停", "恢复", "终止"][i]}</button>)}
            <span className="pill">{labels[session.status] ?? session.status}</span>
          </div>
          {leader && <label className="assign">负责人 <select aria-label="任务负责人" value={task.owner_id} disabled={offline || busy || task.status === "in_progress"}
            onChange={e => void post(p + `/tasks/${task.task_id}/assign`, { user_id: e.target.value })}>
            {members.map(m => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}</select></label>}
          {!canExecute && !offline && <p className="muted">仅负责人和组长可以操作此任务及查看日志。</p>}
          <div className="tabs">{["logs", "changes", "tests"].map((key, i) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{["实时日志", "代码变更", `测试 · ${labels[tests.status] ?? tests.status}`][i]}</button>)}</div>
          {session.error && <p className="error">{session.error}</p>}
          {tab === "logs" && <pre className="terminal">{logs.length ? logs.map(l => `[${l.level}] ${l.message}`).join("\n") : "等待 Agent 日志…"}</pre>}
          {tab === "changes" && <><p className="muted">{changes.flatMap(c => c.files).join(" · ") || "尚无文件变更"}</p>
            <pre className="terminal">{changes.map(c => c.diff).join("\n") || "暂无 Diff"}</pre>
            <p className="muted">提交 {changes.map(c => c.commit_hash).filter(Boolean).join(", ") || "未提交"}</p>
            <div className="toolbar"><button disabled={busy || !canExecute || task.status !== "completed"} onClick={() => void post(t + "/commit", { message: "MVP: complete task" })}>提交授权变更</button>
              <button disabled={busy || offline || !leader || task.status !== "completed"} onClick={() => void post(p + `/tasks/${task.task_id}/merge`, { message: "MVP: review and merge task" })}>组长审查并合并</button></div></>}
          {tab === "tests" && <><button disabled={busy || !canExecute || !task.workspace_path || task.status === "in_progress"}
            onClick={() => void act(async () => setTests(await request<TestResult>(t + "/tests", token, {})))}>运行工作区真实测试</button>
            <pre className="terminal">{tests.output ?? "尚未运行测试；结果来自任务工作区实际 pytest 输出。"}</pre></>}
          <details><summary>验收条件与工作区</summary><p>{task.acceptance_criteria.join("；")}</p><code>{task.workspace_path ?? "运行后创建独立 Worktree"}</code><p>{task.branch_name}</p></details>
        </> : <p className="empty">从任务看板选择一个任务。</p>}
      </section>
    </div>
    <section className="panel interfaces"><div className="section-head"><h2>04 / 接口与自动文档</h2><span>C · AST + WebSocket</span></div>
      <div className="toolbar"><input aria-label="搜索接口" placeholder="搜索函数、模块或说明" value={query} onChange={e => setQuery(e.target.value)} />
        <button disabled={busy || offline || !token} onClick={() => void post(p + "/interfaces/refresh")}>重新扫描</button>
        <button disabled={busy || (!offline && !token)} onClick={() => void act(() => offline ? Promise.resolve(save(demo.interfaces.map(signature).join("\n"))) : download(p + "/interfaces?format=markdown", token))}>下载完整文档</button></div>
      <div className="interface-grid"><div className="interface-list">{filtered.map(i => <button key={i.interface_id} className={info?.interface_id === i.interface_id ? "selected" : ""}
        onClick={() => setInterfaceId(i.interface_id)}><code>{i.name}</code><small>{i.module} · v{i.version}</small></button>)}
        {!filtered.length && <p className="empty">暂无匹配接口。</p>}</div><div className="interface-detail">{info && <>
          <pre className="signature">{signature(info)}</pre><p>{info.docstring ?? "暂无 docstring"}</p>
          <p className="muted">{info.file_path} · {info.kind} · v{info.version}</p>
          <p>静态调用依赖：{info.dependencies.join("、") || "无可解析的导入调用"}</p>
          <details><summary>版本历史 · {versions.length} 条</summary>{versions.map((v, i) => <div className="version" key={i}>
            <small>v{v.version} · {v.snapshot.is_deleted ? "删除" : "注册/更新"} · {v.snapshot.commit_hash?.slice(0, 7) ?? "未提交"}</small><code>{signature(v.snapshot)}</code></div>)}</details>
        </>}</div></div>
      <details className="semantic"><summary>Agent 模块说明与变更记录 {documentation.stale ? "· 代码已变化，需重新生成" : ""}</summary>
        <p className="muted">{offline ? "离线模式不调用模型。" : documentation.configured ? "使用已配置的模型生成说明，并随文档一起导出。" : "尚未配置模型；AST 文档和版本历史照常自动更新。"}</p>
        <button disabled={busy || offline || !documentation.configured} onClick={() => void post(p + "/documentation")}>生成 / 更新 Agent 说明</button>
        {documentation.document && <pre className="notes">{documentation.document.markdown}</pre>}
      </details>
    </section>
    <footer>TeamCode Agent · 课程小组项目 <span>{offline ? "离线样例" : "真实后端"} / 修改 Python 文件后，接口自动更新</span></footer>
  </main>;
}
