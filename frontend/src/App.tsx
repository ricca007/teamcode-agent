import { useEffect, useState } from "react";

import { AgentPanel } from "./components/AgentPanel";
import { ApiKeysPanel } from "./components/ApiKeysPanel";
import { AppShell, type ViewKey } from "./components/AppShell";
import { ChangesPanel } from "./components/ChangesPanel";
import { Dashboard } from "./components/Dashboard";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { InterfaceBrowser } from "./components/InterfaceBrowser";
import { TeamPanel } from "./components/TeamPanel";
import { useProjectSocket } from "./hooks/useProjectSocket";
import { useAppStore } from "./store/useAppStore";

export default function App() {
  const [view, setView] = useState<ViewKey>("dashboard");
  const projectId = useAppStore((state) => state.projectId);
  const load = useAppStore((state) => state.load);
  const hasActiveTask = useAppStore((state) =>
    state.tasks.some((task) => task.status === "in_progress"),
  );

  useEffect(() => {
    void load();
  }, [load, projectId]);

  // 任务运行期间静默轮询，让会话状态/日志及时可见，同时不打断用户操作
  useEffect(() => {
    if (!hasActiveTask) {
      return;
    }
    const timer = window.setInterval(() => {
      void load(true);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveTask, load]);

  useProjectSocket();

  return (
    <AppShell view={view} onNavigate={setView}>
      <ErrorBoundary key={view}>
        {view === "dashboard" ? (
          <Dashboard onOpenAgents={() => setView("agents")} />
        ) : null}
        {view === "agents" ? <AgentPanel /> : null}
        {view === "interfaces" ? <InterfaceBrowser /> : null}
        {view === "changes" ? <ChangesPanel /> : null}
        {view === "apikeys" ? <ApiKeysPanel /> : null}
        {view === "team" ? <TeamPanel /> : null}
      </ErrorBoundary>
    </AppShell>
  );
}
