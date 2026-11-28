import { useEffect, type ReactNode } from "react";

import { getAgents, setAuthToken } from "../api/client";
import { useT, type TKey } from "../i18n";
import { useAppStore } from "../store/useAppStore";
import type { ConnectionState } from "../types";
import { LanguageToggle } from "./LanguageToggle";

export type ViewKey =
  | "dashboard"
  | "agents"
  | "interfaces"
  | "changes"
  | "apikeys"
  | "team";

const NAV: Array<{ key: ViewKey; label: TKey; hint: TKey }> = [
  { key: "dashboard", label: "nav.dashboard", hint: "nav.dashboardHint" },
  { key: "agents", label: "nav.agents", hint: "nav.agentsHint" },
  { key: "interfaces", label: "nav.interfaces", hint: "nav.interfacesHint" },
  { key: "changes", label: "nav.changes", hint: "nav.changesHint" },
  { key: "apikeys", label: "nav.apikeys", hint: "nav.apikeysHint" },
];

const LEADER_NAV = {
  key: "team" as ViewKey,
  label: "nav.team" as TKey,
  hint: "nav.teamHint" as TKey,
};

const CONNECTION_COPY: Record<ConnectionState, TKey> = {
  open: "conn.open",
  connecting: "conn.connecting",
  closed: "conn.closed",
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
  const t = useT();

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
  const projectName = currentProject?.name ?? projectId ?? t("shell.noTeam");
  const currentLabel = t(
    nav.find((item) => item.key === view)?.label ?? "shell.workspace",
  );
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
        {t("shell.skip")}
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <BrandMark />
            <div>
              <p className="brand__name">TeamCode</p>
              <p className="brand__sub">{t("shell.subtitle")}</p>
            </div>
          </div>

          <div className="project-block">
            <p className="eyebrow">{t("shell.currentProject")}</p>
            <p className="project-block__name">{projectName}</p>
            <p className="project-block__id mono">
              {userName ?? t("shell.notLoggedIn")} ·{" "}
              {role === "leader"
                ? t("role.leader")
                : role === "member"
                  ? t("role.member")
                  : t("role.unknown")}
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
                aria-label={t("shell.switchTeam")}
              >
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {t("shell.teamOption", {
                      name: item.name,
                      role:
                        item.role === "leader"
                          ? t("role.leader")
                          : t("role.member"),
                    })}
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
                {t("shell.logout")}
              </button>
            </div>
          </div>

          <nav className="nav" aria-label={t("shell.mainNav")}>
            <p className="eyebrow nav__label">{t("shell.workspace")}</p>
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
                  <span className="nav__title">{t(item.label)}</span>
                  <span className="nav__hint">{t(item.hint)}</span>
                </span>
                <span className="nav__count mono">{counts[item.key]}</span>
              </button>
            ))}
          </nav>

          <div className="sidebar__footer">
            <p className={`conn conn--${connection}`} role="status">
              <span className="conn__dot" aria-hidden="true" />
              {t(CONNECTION_COPY[connection])}
            </p>
            <p className="sidebar__meta mono">
              {t("shell.eventChannel", { projectId })}
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
              <LanguageToggle />
              <label className="agent-select">
                <span className="sr-only">{t("shell.selectAgent")}</span>
                <select
                  value={selectedAgent}
                  onChange={(event) => setSelectedAgent(event.target.value)}
                  aria-label={t("shell.selectAgent")}
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
                        {agent.available ? "" : t("shell.notInstalled")}
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
                aria-label={t("shell.refreshData")}
                title={t("shell.refreshData")}
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
