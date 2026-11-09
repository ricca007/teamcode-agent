import { create } from "zustand";

import {
  getInterfaces,
  loadLiveBundle,
  type AgentInfo,
  type ProjectSummary,
} from "../api/client";
import type {
  AgentSession,
  ChangeSet,
  ConnectionState,
  InterfaceInfo,
  LogEntry,
  Task,
  WSEvent,
} from "../types";

const DEFAULT_PROJECT_ID = import.meta.env.VITE_PROJECT_ID ?? "p_001";

let loadToken = 0;

/** 任务进入这些状态后，会话/日志/变更已经落库，重新拉取一次完整数据。 */
const TERMINAL_TASK_STATUSES = new Set<Task["status"]>([
  "completed",
  "blocked",
  "cancelled",
]);

function logId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

export interface AppState {
  projectId: string;
  role: "leader" | "member" | null;
  userName: string | null;
  userId: string | null;
  projects: ProjectSummary[];
  agents: AgentInfo[];
  selectedAgent: string;
  tasks: Task[];
  sessions: AgentSession[];
  logs: LogEntry[];
  interfaces: InterfaceInfo[];
  changes: ChangeSet[];
  loading: boolean;
  error: string | null;
  connection: ConnectionState;
  interfaceQuery: string;
  interfaceKind: InterfaceInfo["kind"] | "all";
  selectedInterfaceId: string | null;

  setProjectId: (projectId: string) => void;
  setAuth: (
    role: "leader" | "member",
    name: string,
    userId: string,
  ) => void;
  setProjects: (projects: ProjectSummary[]) => void;
  selectProject: (project: ProjectSummary) => void;
  setAgents: (agents: AgentInfo[]) => void;
  setSelectedAgent: (name: string) => void;
  clearAuth: () => void;
  setConnection: (connection: ConnectionState) => void;
  load: (silent?: boolean) => Promise<void>;
  handleEvent: (event: WSEvent) => void;
  appendLog: (entry: LogEntry) => void;
  setInterfaceQuery: (query: string) => void;
  setInterfaceKind: (kind: InterfaceInfo["kind"] | "all") => void;
  selectInterface: (interfaceId: string | null) => void;
}

const emptyData = {
  tasks: [] as Task[],
  sessions: [] as AgentSession[],
  logs: [] as LogEntry[],
  interfaces: [] as InterfaceInfo[],
  changes: [] as ChangeSet[],
  selectedInterfaceId: null,
};

export const useAppStore = create<AppState>((set, get) => ({
  projectId: DEFAULT_PROJECT_ID,
  role: null,
  userName: null,
  userId: null,
  projects: [],
  agents: [],
  selectedAgent:
    (typeof window !== "undefined"
      ? window.localStorage.getItem("tc_agent")
      : null) ?? "claude",
  ...emptyData,
  loading: true,
  error: null,
  connection: "connecting",
  interfaceQuery: "",
  interfaceKind: "all",

  setAuth: (role, name, userId) => set({ role, userName: name, userId }),

  setProjects: (projects) => set({ projects }),

  selectProject: (project) => {
    window.localStorage.setItem("tc_project_id", project.id);
    set({
      projectId: project.id,
      role: project.role,
      ...emptyData,
      loading: true,
      error: null,
    });
  },

  setAgents: (agents) => set({ agents }),

  setSelectedAgent: (name) => {
    window.localStorage.setItem("tc_agent", name);
    set({ selectedAgent: name });
  },

  clearAuth: () =>
    set({ role: null, userName: null, userId: null, projects: [] }),

  setProjectId: (projectId) => {
    if (projectId === get().projectId) {
      return;
    }
    set({
      projectId,
      ...emptyData,
      loading: true,
      error: null,
    });
  },

  setConnection: (connection) => set({ connection }),

  load: async (silent = false) => {
    const token = ++loadToken;
    const { projectId, selectedInterfaceId } = get();
    if (!silent) {
      set({ loading: true, error: null });
    }

    try {
      const live = await loadLiveBundle(projectId);
      if (token !== loadToken) {
        return;
      }
      set({
        tasks: live.tasks,
        sessions: live.sessions,
        logs: live.logs,
        interfaces: live.interfaces,
        changes: live.changes,
        loading: false,
        error:
          live.warnings.length > 0
            ? `${live.warnings.join(" ")} 部分模块可能尚未上线。`
            : null,
        selectedInterfaceId:
          selectedInterfaceId ?? live.interfaces[0]?.interface_id ?? null,
      });
    } catch (error) {
      if (token !== loadToken) {
        return;
      }
      console.error("[TeamCode] 加载项目数据失败", error);
      set({
        loading: false,
        error: error instanceof Error ? error.message : "加载项目数据失败",
      });
    }
  },

  appendLog: (entry) =>
    set((state) => ({ logs: [...state.logs, entry].slice(-400) })),

  handleEvent: (event) => {
    const state = get();
    if (event.project_id !== state.projectId) {
      return;
    }

    switch (event.type) {
      case "task.updated": {
        const payload = event.payload as { task?: Task } & Partial<Task>;
        const task = (payload.task ?? payload) as Task;
        if (!task?.task_id) {
          return;
        }
        const previous = state.tasks.find(
          (item) => item.task_id === task.task_id,
        );
        if (!previous) {
          // 队长刚把任务分配给当前成员：加入看板并拉取会话/日志
          if (task.owner_id && task.owner_id === state.userId) {
            set((current) => ({ tasks: [...current.tasks, task] }));
            void get().load(true);
          }
          return;
        }
        set((current) => ({
          tasks: current.tasks.map((item) =>
            item.task_id === task.task_id ? { ...item, ...task } : item,
          ),
        }));
        if (
          task.status &&
          TERMINAL_TASK_STATUSES.has(task.status) &&
          previous?.status !== task.status
        ) {
          // 任务结束时补拉一次会话、日志、变更，避免只更新看板
          void get().load(true);
        }
        return;
      }

      case "agent.log": {
        const payload = event.payload as Partial<LogEntry>;
        if (!payload?.message) {
          return;
        }
        state.appendLog({
          id: payload.id ?? logId("log"),
          session_id: payload.session_id ?? "",
          task_id: payload.task_id ?? event.task_id ?? "",
          ts: payload.ts ?? event.ts,
          level: payload.level ?? "info",
          message: payload.message,
        });
        return;
      }

      case "interface.updated": {
        void getInterfaces(state.projectId)
          .then((interfaces) => set({ interfaces }))
          .catch(() => {
            // 接口刷新失败不打断页面，下一次事件会重试
          });
        return;
      }

      case "code.changed": {
        const payload = event.payload as Partial<ChangeSet>;
        if (!payload?.files?.length) {
          return;
        }
        const change: ChangeSet = {
          id: payload.id ?? logId("change"),
          task_id: payload.task_id ?? event.task_id ?? "",
          files: payload.files,
          diff: payload.diff ?? "",
          commit_hash: payload.commit_hash ?? null,
          ts: payload.ts ?? event.ts,
        };
        set((current) => ({ changes: [change, ...current.changes] }));
        return;
      }
    }
  },

  setInterfaceQuery: (query) => set({ interfaceQuery: query }),
  setInterfaceKind: (kind) => set({ interfaceKind: kind }),
  selectInterface: (interfaceId) => set({ selectedInterfaceId: interfaceId }),
}));
