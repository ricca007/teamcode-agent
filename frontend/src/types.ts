/** 与 docs/interface_contract.md、backend/app/schemas/core.py 对齐的前端数据契约。 */

/** A 负责的任务状态（tasks.status）。 */
export type TaskStatus =
  | "planned"
  | "in_progress"
  | "blocked"
  | "completed"
  | "cancelled";

/** B 负责的 Agent 会话状态（agent_sessions.status）。 */
export type AgentStatus =
  | "pending"
  | "running"
  | "paused"
  | "succeeded"
  | "failed"
  | "terminated";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface Task {
  task_id: string;
  project_id: string;
  title: string;
  description: string;
  owner_id: string;
  owner_name?: string;
  status: TaskStatus;
  allowed_paths: string[];
  interface_requirements?: string[];
  acceptance_criteria?: string[];
  depends_on: string[];
  priority: number;
  replan_version: number;
  workspace_path?: string | null;
  branch_name?: string | null;
}

export interface ParamInfo {
  name: string;
  annotation: string | null;
  default: string | null;
}

export interface InterfaceInfo {
  interface_id: string;
  project_id: string;
  module: string;
  file_path: string;
  name: string;
  kind: "function" | "method" | "class";
  params: ParamInfo[];
  returns: string | null;
  docstring: string | null;
  version: number;
  commit_hash: string | null;
  dependencies: string[];
  lineno?: number | null;
  decorators?: string[];
  is_async?: boolean;
}

export interface InterfaceListResponse {
  project_id: string;
  generated_at: string;
  count: number;
  interfaces: InterfaceInfo[];
}

export interface AgentSession {
  session_id: string;
  task_id: string;
  adapter: string;
  status: AgentStatus;
  workspace: string;
  started_at: string;
  ended_at?: string | null;
}

export interface LogEntry {
  id: string;
  session_id: string;
  task_id: string;
  ts: string;
  level: LogLevel;
  message: string;
  sequence?: number;
}

export interface ChangeSet {
  id: string;
  task_id: string;
  files: string[];
  diff: string;
  commit_hash: string | null;
  ts: string;
}

export type WSEventType =
  | "task.updated"
  | "agent.log"
  | "interface.updated"
  | "code.changed";

export interface WSEvent {
  type: WSEventType;
  project_id: string;
  task_id: string | null;
  payload: unknown;
  ts: string;
}

export type ConnectionState = "connecting" | "open" | "closed";
