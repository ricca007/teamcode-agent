import { useEffect, type ReactNode } from "react";

import { getAgents, setAuthToken } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { ConnectionState } from "../types";

export type ViewKey =
  | "dashboard"
  | "agents"
  | "interfaces"
  | "changes"
  | "apikeys"
  | "team";

const NAV: Array<{ key: ViewKey; label: string; hint: string }> = [
  { key: "dashboard", label: "任务看板", hint: "进度与分配" },
  { key: "agents", label: "Agent 会话", hint: "状态与日志" },
  { key: "interfaces", label: "接口浏览", hint: "签名与版本" },
  { key: "changes", label: "代码变更", hint: "Diff 与提交" },
  { key: "apikeys", label: "API Key", hint: "程序化访问" },
];

const LEADER_NAV = { key: "team" as ViewKey, label: "团队管理", hint: "大纲与分配" };

const CONNECTION_COPY: Record<ConnectionState, string> = {
  open: "实时连接已建立",
  connecting: "正在建立连接",
  closed: "连接中断 · 等待重连",
};

function BrandMark() {
  return (
    <svg
      className="brand__mark"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="1.5"
        y="1.5"
        width="29"
        height="29"
        rx="7"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="10" cy="11" r="2.4" fill="currentColor" />
      <circle cx="22" cy="10" r="2.4" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="16" cy="22" r="2.4" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M12.2 11.9 19.8 10.5M10.9 13.2l4 6.4M20.4 12.2l-3.1 7.3"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function NavIcon({ name }: { name: ViewKey }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "dashboard":
      return (
        <svg {...common}>
          <rect x="2" y="2" width="5" height="5" rx="1" />
          <rect x="9" y="2" width="5" height="5" rx="1" />
          <rect x="2" y="9" width="5" height="5" rx="1" />
          <rect x="9" y="9" width="5" height="5" rx="1" />
        </svg>
      );
    case "agents":
      return (
        <svg {...common}>
          <rect x="2" y="3" width="12" height="10" rx="1.5" />
          <path d="M4.5 6.5l2 1.5-2 1.5M8 10h3.5" />
        </svg>
      );
    case "interfaces":
      return (
        <svg {...common}>
          <path d="M5.5 3.5 3 8l2.5 4.5M10.5 3.5 13 8l-2.5 4.5" />
        </svg>
      );
    case "changes":
      return (
        <svg {...common}>
          <path d="M4 3v7.5A2.5 2.5 0 0 0 6.5 13H13" />
          <path d="M12 3v7.5A2.5 2.5 0 0 1 9.5 13H3" />
          <path d="M2 6h4M10 10h4" />
        </svg>
      );
    case "team":
      return (
        <svg {...common}>
          <circle cx="6" cy="5.5" r="2.2" />
          <circle cx="11" cy="7" r="1.8" />
          <path d="M2.5 13c.4-2.2 1.8-3.5 3.5-3.5S9.1 10.8 9.5 13" />
          <path d="M10 10.3c1.6.1 2.8 1.1 3.2 2.7" />
        </svg>
      );
    case "apikeys":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="3.2" />
          <path d="M10.4 10.4 14 14M12 12l-1 1M13 13l-1 1" />
        </svg>
      );
  }
}

export function RefreshIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
      <path d="M13.5 2.5v3.2h-3.2" />
    </svg>
  );
}

export function AppShell({
  view,
  onNavigate,
  children,
}: {
  view: ViewKey;
  onNavigate: (view: ViewKey) => void;
  children: ReactNode;
}) {
  const loading = useAppStore((state) => state.loading);
  const connection = useAppStore((state) => state.connection);
  const projectId = useAppStore((state) => state.projectId);
  const tasks = useAppStore((state) => state.tasks);
  const sessions = useAppStore((state) => state.sessions);
  const interfaces = useAppStore((state) => state.interfaces);
  const changes = useAppStore((state) => state.changes);
  const role = useAppStore((state) => state.role);
  const userName = useAppStore((state) => state.userName);
  const projects = useAppStore((state) => state.projects);
  const selectProject = useAppStore((state) => state.selectProject);
  const clearAuth = useAppStore((state) => state.clearAuth);
  const agents = useAppStore((state) => state.agents);
  const selectedAgent = useAppStore((state) => state.selectedAgent);
  const setAgents = useAppStore((state) => state.setAgents);
  const setSelectedAgent = useAppStore((state) => state.setSelectedAgent);
  const load = useAppStore((state) => state.load);

  useEffect(() => {
    void getAgents()
      .then((list) => {
        setAgents(list);
        const current = list.find((item) => item.name === selectedAgent);
        if (!current?.available) {
          const fallback = list.find((item) => item.available);
          if (fallback) {
            setSelectedAgent(fallback.name);
          }
        }
      })
      .catch((agentsError) => {
        console.warn("[TeamCode] 无法加载 Agent 列表", agentsError);
      });
  }, [setAgents, setSelectedAgent, selectedAgent]);

  const nav = role === "leader" ? [...NAV, LEADER_NAV] : NAV;
  const currentProject = projects.find((item) => item.id === projectId);
  const projectName = currentProject?.name ?? projectId ?? "未选择团队";
  const currentLabel = nav.find((item) => item.key === view)?.label ?? "工作区";
  const counts: Record<ViewKey, number> = {
    dashboard: tasks.length,
    agents: sessions.length,
    interfaces: interfaces.length,
    changes: changes.length,
    apikeys: 0,
    team: 0,
  };

  const handleLogout = () => {
    setAuthToken("");
    window.localStorage.removeItem("tc_join_request");
    clearAuth();
    window.location.reload();
  };

  return (
    <>
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <BrandMark />
            <div>
              <p className="brand__name">TeamCode</p>
              <p className="brand__sub">Agent 协作台</p>
            </div>
          </div>

          <div className="project-block">
            <p className="eyebrow">当前项目</p>
            <p className="project-block__name">{projectName}</p>
            <p className="project-block__id mono">
              {userName ?? "未登录"} ·{" "}
              {role === "leader" ? "队长" : role === "member" ? "组员" : "未知角色"}
            </p>
            {projects.length > 1 ? (
              <select
                className="project-block__input mono"
                value={projectId}
                onChange={(event) => {
                  const next = projects.find(
                    (item) => item.id === event.target.value,
                  );
                  if (next) {
                    selectProject(next);
                  }
                }}
                aria-label="切换团队"
              >
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}（{item.role === "leader" ? "队长" : "组员"}）
                  </option>
                ))}
              </select>
            ) : null}
            <div className="project-block__switch">
              <button
                type="button"
                className="btn btn--tiny"
                onClick={handleLogout}
              >
                退出账号
              </button>
            </div>
          </div>

          <nav className="nav" aria-label="主导航">
            <p className="eyebrow nav__label">工作区</p>
            {nav.map((item) => (
              <button
                key={item.key}
                type="button"
                className="nav__item"
                aria-current={view === item.key ? "page" : undefined}
                onClick={() => onNavigate(item.key)}
              >
                <NavIcon name={item.key} />
                <span className="nav__text">
                  <span className="nav__title">{item.label}</span>
                  <span className="nav__hint">{item.hint}</span>
                </span>
                <span className="nav__count mono">{counts[item.key]}</span>
              </button>
            ))}
          </nav>

          <div className="sidebar__footer">
            <p className={`conn conn--${connection}`} role="status">
              <span className="conn__dot" aria-hidden="true" />
              {CONNECTION_COPY[connection]}
            </p>
            <p className="sidebar__meta mono">
              事件通道 /ws/projects/{projectId}
            </p>
          </div>
        </aside>

        <main className="main" id="main-content">
          <header className="topbar">
            <div className="topbar__crumbs">
              <span>{projectName}</span>
              <span className="crumb__sep" aria-hidden="true">
                /
              </span>
              <span className="crumb__current">{currentLabel}</span>
            </div>
            <div className="topbar__actions">
              <label className="agent-select">
                <span className="sr-only">选择 Coding Agent</span>
                <select
                  value={selectedAgent}
                  onChange={(event) => setSelectedAgent(event.target.value)}
                  aria-label="选择 Coding Agent"
                >
                  {agents.length === 0 ? (
                    <option value={selectedAgent}>{selectedAgent}</option>
                  ) : (
                    agents.map((agent) => (
                      <option
                        key={agent.name}
                        value={agent.name}
                        disabled={!agent.available}
                      >
                        {agent.name}
                        {agent.available ? "" : "（未安装）"}
                      </option>
                    ))
                  )}
                </select>
              </label>
              <button
                type="button"
                className={`btn btn--ghost btn--icon${loading ? " is-spinning" : ""}`}
                onClick={() => void load()}
                disabled={loading}
                aria-label="刷新项目数据"
                title="刷新项目数据"
              >
                <RefreshIcon />
              </button>
            </div>
          </header>

          <div className="content">{children}</div>
        </main>
      </div>
    </>
  );
}
