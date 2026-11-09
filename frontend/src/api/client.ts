/**
 * 统一 API client（实时模式）。
 *
 * 所有网络细节（地址、错误包、响应包裹层）都收敛在这里，组件只消费领域对象。
 * 默认使用同源相对路径：开发时由 Vite 代理 /api、/ws 到后端，避免 CORS。
 * 部署在独立域名时，通过 VITE_API_BASE / VITE_WS_BASE 显式指定。
 */

import type {
  AgentSession,
  ChangeSet,
  InterfaceInfo,
  InterfaceListResponse,
  LogEntry,
  Task,
} from "../types";

const rawApiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function defaultWsBase(): string {
  if (rawApiBase) {
    return rawApiBase.replace(/^http/, "ws");
  }
  if (typeof window === "undefined") {
    return "ws://127.0.0.1:8000";
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}`;
}

export const API_BASE = rawApiBase;
export const WS_BASE = (import.meta.env.VITE_WS_BASE ?? defaultWsBase()).replace(
  /\/$/,
  "",
);

const TOKEN_KEY = "tc_token";
let authToken =
  typeof window === "undefined"
    ? ""
    : window.localStorage.getItem(TOKEN_KEY) ?? "";

export function getAuthToken(): string {
  return authToken;
}

export function setAuthToken(token: string): void {
  authToken = token;
  if (typeof window === "undefined") {
    return;
  }
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  Object.assign(headers, init?.headers ?? {});
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    });
  } catch {
    throw new ApiError(`无法连接后端 ${API_BASE || "（同源）"}`, 0, "network_error");
  }

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const body = (await response.json()) as {
        code?: string;
        message?: string;
        detail?: unknown;
      };
      code = body.code ?? code;
      message = body.message ?? message;
    } catch {
      // 非 JSON 错误体，保留默认信息
    }
    throw new ApiError(message, response.status, code);
  }

  return (await response.json()) as T;
}

function pickArray<T>(value: unknown, key: string): T[] {
  if (Array.isArray(value)) {
    return value as T[];
  }
  if (value && typeof value === "object") {
    const nested = (value as Record<string, unknown>)[key];
    if (Array.isArray(nested)) {
      return nested as T[];
    }
  }
  return [];
}

export async function getTasks(projectId: string): Promise<Task[]> {
  const data = await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/tasks`,
  );
  return pickArray<Task>(data, "tasks");
}

export async function getInterfaces(projectId: string): Promise<InterfaceInfo[]> {
  const data = await requestJson<InterfaceListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/interfaces?format=json`,
  );
  return data.interfaces ?? [];
}

export interface AgentInfo {
  name: string;
  kind: string;
  prompt_mode: string;
  available: boolean;
}

export async function getAgents(): Promise<AgentInfo[]> {
  const data = await requestJson<{ agents: AgentInfo[] }>("/api/agents");
  return data.agents ?? [];
}

export async function runTask(
  taskId: string,
  agentName?: string,
): Promise<void> {
  await requestJson<unknown>(`/api/tasks/${encodeURIComponent(taskId)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(agentName ? { agent_name: agentName } : {}),
  });
}

export async function sendTaskMessage(
  taskId: string,
  message: string,
): Promise<void> {
  await requestJson<unknown>(
    `/api/tasks/${encodeURIComponent(taskId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
}

export type TaskAction = "pause" | "resume" | "terminate";

export async function controlTask(
  taskId: string,
  action: TaskAction,
): Promise<void> {
  await requestJson<unknown>(
    `/api/tasks/${encodeURIComponent(taskId)}/${action}`,
    { method: "POST" },
  );
}

export interface Me {
  user_id: string;
  name: string;
}

export async function getMe(): Promise<Me> {
  return requestJson<Me>("/api/me");
}

export interface AuthResult {
  token: string;
  user: { id: string; name: string; email: string };
}

export async function registerAccount(payload: {
  name: string;
  email: string;
  password: string;
}): Promise<AuthResult> {
  return requestJson<AuthResult>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function loginAccount(payload: {
  email: string;
  password: string;
}): Promise<AuthResult> {
  return requestJson<AuthResult>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface ProjectSummary {
  id: string;
  name: string;
  repo_path: string;
  role: "leader" | "member";
}

export async function getMyProjects(): Promise<ProjectSummary[]> {
  const data = await requestJson<{ projects: ProjectSummary[] }>(
    "/api/projects",
  );
  return data.projects ?? [];
}

export interface CreateProjectResult {
  id: string;
  name: string;
  repo_path: string;
  owner_id: string;
  role: "leader" | "member";
}

export async function createProject(payload: {
  name: string;
  repo_path: string;
}): Promise<CreateProjectResult> {
  return requestJson<CreateProjectResult>("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function joinTeam(
  projectId: string,
  areas: string[] = [],
): Promise<void> {
  await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/join-requests`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ areas }),
    },
  );
}

export interface MergeResult {
  task_id: string;
  branch: string;
  base_branch: string;
  commit_hash: string | null;
  merge_commit: string | null;
  interfaces: {
    total_interfaces?: number;
    added?: string[];
    updated?: string[];
    deleted?: string[];
    error?: string;
  };
}

export async function mergeTask(
  projectId: string,
  taskId: string,
  message = "merge task",
): Promise<MergeResult> {
  return requestJson<MergeResult>(
    `/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/merge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
}

export interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  project_id: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface CreatedApiKey extends ApiKeyRow {
  raw_key: string;
}

export async function createApiKey(
  name: string,
  projectId?: string,
): Promise<CreatedApiKey> {
  return requestJson<CreatedApiKey>("/api/auth/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, project_id: projectId ?? null }),
  });
}

export async function listApiKeys(): Promise<ApiKeyRow[]> {
  const data = await requestJson<{ keys: ApiKeyRow[] }>(
    "/api/auth/api-keys",
  );
  return data.keys ?? [];
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await requestJson<unknown>(
    `/api/auth/api-keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" },
  );
}

export interface MyJoinRequest {
  request_id: string;
  project_id: string;
  project_name: string;
  status: string;
  areas: string[];
  created_at: string;
}

export async function getMyJoinRequests(): Promise<MyJoinRequest[]> {
  const data = await requestJson<{ requests: MyJoinRequest[] }>(
    "/api/join-requests/mine",
  );
  return data.requests ?? [];
}

export interface JoinRequestResult {
  request_id: string;
  project_id: string;
  status: string;
  display_name: string;
  user_id?: string | null;
  role?: string | null;
  token?: string;
}

export async function createJoinRequest(payload: {
  project_id: string;
  display_name: string;
  device_id: string;
  device_secret: string;
}): Promise<JoinRequestResult> {
  return requestJson<JoinRequestResult>("/api/join-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getJoinStatus(
  requestId: string,
  deviceSecret: string,
): Promise<JoinRequestResult> {
  return requestJson<JoinRequestResult>(
    `/api/join-requests/${encodeURIComponent(requestId)}`,
    { headers: { "X-Device-Secret": deviceSecret } },
  );
}

export interface JoinRequestRow {
  request_id: string;
  project_id: string;
  device_id: string;
  display_name: string;
  areas: string[];
  status: string;
  user_id: string | null;
  created_at: string;
}

export async function listJoinRequests(
  projectId: string,
): Promise<JoinRequestRow[]> {
  const data = await requestJson<{ requests: JoinRequestRow[] }>(
    `/api/projects/${encodeURIComponent(projectId)}/join-requests`,
  );
  return data.requests ?? [];
}

export async function approveJoinRequest(
  projectId: string,
  requestId: string,
  areas: string[],
): Promise<void> {
  await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/join-requests/${encodeURIComponent(requestId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ areas }),
    },
  );
}

export async function rejectJoinRequest(
  projectId: string,
  requestId: string,
): Promise<void> {
  await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/join-requests/${encodeURIComponent(requestId)}/reject`,
    { method: "POST" },
  );
}

export interface MemberRow {
  project_id: string;
  user_id: string;
  name: string;
  email: string;
  role: string;
}

export async function getMembers(projectId: string): Promise<MemberRow[]> {
  const data = await requestJson<{ members: MemberRow[] }>(
    `/api/projects/${encodeURIComponent(projectId)}/members`,
  );
  return data.members ?? [];
}

export async function assignTask(
  projectId: string,
  taskId: string,
  userId: string,
): Promise<void> {
  await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/assign`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    },
  );
}

export async function submitRequirements(
  projectId: string,
  requirements: string,
  roles: string[],
  mode: "plan" | "replan" = "plan",
): Promise<unknown> {
  return requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/requirements`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirements, roles, mode }),
    },
  );
}

export async function refreshInterfaces(projectId: string): Promise<void> {
  await requestJson<unknown>(
    `/api/projects/${encodeURIComponent(projectId)}/interfaces/refresh`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
  );
}

export async function getTaskStatus(taskId: string): Promise<AgentSession | null> {
  const data = await requestJson<unknown>(
    `/api/tasks/${encodeURIComponent(taskId)}/status`,
  );
  if (!data || typeof data !== "object") {
    return null;
  }

  const record = data as Record<string, unknown>;
  const nested = record.session;
  if (nested && typeof nested === "object") {
    return nested as AgentSession;
  }

  // B 的 ExecutionAPI 可能只返回状态字符串；这里归一成会话对象
  if (typeof record.status === "string") {
    return {
      session_id: String(record.session_id ?? record.task_or_session_id ?? taskId),
      task_id: String(record.task_id ?? taskId),
      adapter: String(record.adapter ?? "unknown"),
      status: record.status as AgentSession["status"],
      workspace: String(record.workspace ?? ""),
      started_at: String(record.started_at ?? new Date().toISOString()),
      ended_at: (record.ended_at as string | null | undefined) ?? null,
    };
  }
  return null;
}

export async function getTaskLogs(taskId: string): Promise<LogEntry[]> {
  const data = await requestJson<unknown>(`/api/tasks/${encodeURIComponent(taskId)}/logs`);
  const rows = pickArray<Record<string, unknown>>(data, "logs");
  return rows.map((row, index) => ({
    id: String(row.id ?? `${row.session_id ?? taskId}-${row.sequence ?? index}`),
    session_id: String(row.session_id ?? ""),
    task_id: String(row.task_id ?? taskId),
    ts: String(row.ts ?? new Date().toISOString()),
    level: (row.level as LogEntry["level"]) ?? "info",
    message: String(row.message ?? ""),
    sequence: typeof row.sequence === "number" ? row.sequence : index,
  }));
}

export async function getTaskChanges(taskId: string): Promise<ChangeSet[]> {
  const data = await requestJson<unknown>(
    `/api/tasks/${encodeURIComponent(taskId)}/changes`,
  );
  const rows = pickArray<Record<string, unknown>>(data, "changes");
  const candidates =
    rows.length > 0
      ? rows
      : data && typeof data === "object" &&
          typeof (data as Record<string, unknown>).changes === "object" &&
          (data as Record<string, unknown>).changes !== null
        ? [(data as Record<string, unknown>).changes as Record<string, unknown>]
        : [];

  return candidates.map((row, index) => ({
    id: String(row.id ?? `${taskId}-change-${index}`),
    task_id: String(row.task_id ?? taskId),
    files: Array.isArray(row.files) ? (row.files as string[]) : [],
    diff: String(row.diff ?? ""),
    commit_hash: (row.commit_hash as string | null | undefined) ?? null,
    ts: String(row.ts ?? new Date().toISOString()),
  }));
}

export interface LiveBundle {
  tasks: Task[];
  sessions: AgentSession[];
  logs: LogEntry[];
  interfaces: InterfaceInfo[];
  changes: ChangeSet[];
  warnings: string[];
}

/**
 * 一次拉取当前项目需要的全部数据。
 *
 * 各子请求互相独立：A/B 的接口尚未上线时，接口注册中心的数据仍然可以
 * 正常展示，只在顶部显示一条非阻断的提示。
 */
export async function loadLiveBundle(projectId: string): Promise<LiveBundle> {
  const warnings: string[] = [];
  const sessions: AgentSession[] = [];
  const logs: LogEntry[] = [];
  const changes: ChangeSet[] = [];

  let tasks: Task[] = [];
  try {
    tasks = await getTasks(projectId);
  } catch (error) {
    warnings.push(`任务接口不可用：${errorMessage(error)}`);
  }

  let interfaces: InterfaceInfo[] = [];
  try {
    interfaces = await getInterfaces(projectId);
  } catch (error) {
    warnings.push(`接口注册中心不可用：${errorMessage(error)}`);
  }

  // 只探测最近的任务，避免页面初次加载发出过多请求
  const candidates = tasks.slice(0, 6);

  await Promise.all(
    candidates.map(async (task) => {
      const [sessionResult, logsResult, changesResult] = await Promise.allSettled([
        getTaskStatus(task.task_id),
        getTaskLogs(task.task_id),
        getTaskChanges(task.task_id),
      ]);

      if (sessionResult.status === "fulfilled" && sessionResult.value) {
        sessions.push(sessionResult.value);
      }
      if (logsResult.status === "fulfilled") {
        logs.push(...logsResult.value);
      }
      if (changesResult.status === "fulfilled") {
        changes.push(...changesResult.value);
      }
    }),
  );

  logs.sort((a, b) => a.ts.localeCompare(b.ts));
  changes.sort((a, b) => b.ts.localeCompare(a.ts));

  return { tasks, sessions, logs, interfaces, changes, warnings };
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "未知错误";
}
