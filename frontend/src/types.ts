export interface Member { user_id: string; name: string; role: "leader" | "member"; token?: string }
export interface Task { task_id: string; title: string; description: string; owner_id: string;
  status: string; allowed_paths: string[]; depends_on: string[]; workspace_path?: string;
  branch_name?: string; acceptance_criteria: string[] }
export interface Interface { interface_id: string; name: string; kind: string; module: string;
  file_path: string; version: number; returns: string | null; docstring: string | null;
  is_async: boolean; commit_hash: string | null; dependencies: string[];
  params: { name: string; annotation: string | null; default: string | null; kind?: string }[] }
export interface Version { version: number; snapshot: Interface & { is_deleted?: boolean }; created_at: string }
export interface Log { message: string; level: string; ts?: string }
export interface TestResult { status: string; output?: string; ts?: string; exit_code?: number }
export interface Session { status: string; adapter?: string; session_id?: string; workspace?: string; error?: string }
export interface Change { files: string[]; diff: string; commit_hash?: string }
export interface Plan { version: number; plan: { tasks: unknown[] }; diff?: { impact_notes: string[];
  added_tasks: string[]; updated_tasks: unknown[]; unchanged_tasks: string[] } | null }
export interface Documentation { configured: boolean; stale: boolean;
  document: { markdown: string; model: string; ts: string } | null }

export const labels: Record<string, string> = { planned: "待开始", in_progress: "进行中", completed: "已完成",
  cancelled: "已取消", blocked: "待处理", pending: "未运行", running: "运行中", paused: "已暂停",
  succeeded: "已完成", failed: "失败", terminated: "已终止", passed: "通过", timeout: "超时", not_run: "未运行" };

export function signature(info: Interface): string {
  const parts: string[] = [];
  let keyword = false;
  info.params.forEach((p, i) => {
    if (p.kind === "keyword_only" && !keyword) { parts.push("*"); keyword = true; }
    if (p.name.startsWith("*")) keyword = true;
    parts.push(p.name + (p.annotation ? `: ${p.annotation}` : "") + (p.default != null ? ` = ${p.default}` : ""));
    if (p.kind === "positional_only" && info.params[i + 1]?.kind !== "positional_only") parts.push("/");
  });
  return `${info.kind === "class" ? "class" : info.is_async ? "async def" : "def"} ${info.name}(${parts.join(", ")})${info.returns ? ` -> ${info.returns}` : ""}`;
}
