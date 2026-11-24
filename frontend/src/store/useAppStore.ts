import { create } from "zustand";

import {
  getInterfaces,
  loadLiveBundle,
  loadTaskDetail as fetchTaskDetail,
  RECENT_TASK_LIMIT,
  type AgentInfo,
  type ProjectSummary,
  type TaskDetail,
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

/** 正在拉取详情的任务，避免「加载更早会话」重复请求。 */
const detailInFlight = new Set<string>();

/** 任务进入这些状态后，会话/日志/变更已经落库，重新拉取一次完整数据。 */
const TERMINAL_TASK_STATUSES = new Set<Task["status"]>([
  "completed",
  "blocked",
  "cancelled",
]);

function logId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function compareLogs(a: LogEntry, b: LogEntry): number {
  return a.ts.localeCompare(b.ts) || (a.sequence ?? 0) - (b.sequence ?? 0);
}

/** 把单个任务的详情合并进现有数据，按 id 去重。 */
function applyDetail(
  state: AppState,
  detail: TaskDetail,
): Pick<AppState, "sessions" | "logs" | "changes" | "detailTaskIds"> {
  const sessions = detail.session
    ? [
        ...state.sessions.filter(
          (item) => item.session_id !== detail.session?.session_id,
        ),
        detail.session,
      ]
    : state.sessions;

  const knownLogIds = new Set(state.logs.map((log) => log.id));
  const logs = [
    ...state.logs,
    ...detail.logs.filter((log) => !knownLogIds.has(log.id)),
  ]
    .sort(compareLogs)
    .slice(-400);

  const knownChangeIds = new Set(state.changes.map((change) => change.id));
  const changes = [
    ...state.changes,
    ...detail.changes.filter((change) => !knownChangeIds.has(change.id)),
  ].sort((a, b) => b.ts.localeCompare(a.ts));

  const detailTaskIds = state.detailTaskIds.includes(detail.taskId)
    ? state.detailTaskIds
    : [...state.detailTaskIds, detail.taskId];

  return { sessions, logs, changes, detailTaskIds };
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
  /** 已拉取详情（会话/日志/变更）的任务，用于按需加载更早会话。 */
  detailTaskIds: string[];
  detailLoading: boolean;
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
  loadTaskDetail: (taskId: string) => Promise<void>;
  loadMoreSessions: () => Promise<void>;
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
  detailTaskIds: [] as string[],
  detailLoading: false,
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
    ++loadToken;
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

  clearAuth: () => {
    ++loadToken;
    set({ role: null, userName: null, userId: null, projects: [], ...emptyData });
  },

  setProjectId: (projectId) => {
    if (projectId === get().projectId) {
      return;
    }
    ++loadToken;
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
        detailTaskIds: live.tasks
          .slice(0, RECENT_TASK_LIMIT)
          .map((task) => task.task_id),
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

  loadTaskDetail: async (taskId) => {
    if (detailInFlight.has(taskId)) {
      return;
    }
    const token = loadToken;
    const projectId = get().projectId;
    detailInFlight.add(taskId);
    try {
      const detail = await fetchTaskDetail(taskId);
      if (token !== loadToken || get().projectId !== projectId) {
        return;
      }
      set((state) => applyDetail(state, detail));
    } finally {
      detailInFlight.delete(taskId);
    }
  },

  loadMoreSessions: async () => {
    const state = get();
    if (state.detailLoading) {
      return;
    }
    const loaded = new Set(state.detailTaskIds);
    const remaining = state.tasks.filter((task) => !loaded.has(task.task_id));
    if (remaining.length === 0) {
      return;
    }
    set({ detailLoading: true });
    try {
      await Promise.all(
        remaining.map((task) => get().loadTaskDetail(task.task_id)),
      );
    } finally {
      set({ detailLoading: false });
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
        if (state.role === "member" && task.owner_id && task.owner_id !== state.userId) {
          if (previous) {
            set((current) => ({ tasks: current.tasks.filter((item) => item.task_id !== task.task_id) }));
            void get().load(true);
          }
          return;
        }
        if (!previous) {
          // 队长刚把任务分配给当前成员：加入看板并拉取会话/日志
          if (state.role === "leader" || (task.owner_id && task.owner_id === state.userId)) {
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
        const token = loadToken;
        void getInterfaces(state.projectId)
          .then((interfaces) => {
            if (token === loadToken && get().projectId === state.projectId) {
              set({ interfaces });
            }
          })
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
