import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import {
  approveJoinRequest,
  assignTask,
  errorMessage,
  getMembers,
  listJoinRequests,
  mergeTask,
  rejectJoinRequest,
  submitRequirements,
  type JoinRequestRow,
  type MemberRow,
} from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { Task } from "../types";
import { ErrorBanner } from "./States";

export function TeamPanel() {
  const projectId = useAppStore((state) => state.projectId);
  const tasks = useAppStore((state) => state.tasks);
  const load = useAppStore((state) => state.load);

  const [outline, setOutline] = useState("");
  const [roles, setRoles] = useState("A,B,C");
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [requests, setRequests] = useState<JoinRequestRow[]>([]);
  const [areas, setAreas] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    const [memberResult, requestResult] = await Promise.allSettled([
      getMembers(projectId),
      listJoinRequests(projectId),
    ]);
    if (memberResult.status === "fulfilled") {
      setMembers(memberResult.value);
    }
    if (requestResult.status === "fulfilled") {
      setRequests(requestResult.value);
    } else {
      setError(errorMessage(requestResult.reason));
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setOutline(await file.text());
    setNotice(`已载入大纲：${file.name}`);
  };

  const handlePlan = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const roleList = roles
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      await submitRequirements(projectId, outline, roleList);
      setNotice("已根据大纲生成任务，可在任务看板分配或直接运行");
      await load(true);
    } catch (planError) {
      setError(errorMessage(planError));
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async (row: JoinRequestRow) => {
    setBusy(true);
    setError(null);
    try {
      const areaList = (areas[row.request_id] ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      await approveJoinRequest(projectId, row.request_id, areaList);
      setNotice(`已批准 ${row.display_name} 加入团队`);
      await refresh();
      await load(true);
    } catch (approveError) {
      setError(errorMessage(approveError));
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async (row: JoinRequestRow) => {
    setBusy(true);
    setError(null);
    try {
      await rejectJoinRequest(projectId, row.request_id);
      setNotice(`已拒绝 ${row.display_name}`);
      await refresh();
    } catch (rejectError) {
      setError(errorMessage(rejectError));
    } finally {
      setBusy(false);
    }
  };

  const handleAssign = async (taskId: string, userId: string) => {
    if (!userId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await assignTask(projectId, taskId, userId);
      setNotice("任务已重新分配");
      await load(true);
    } catch (assignError) {
      setError(errorMessage(assignError));
    } finally {
      setBusy(false);
    }
  };

  const handleMerge = async (task: Task) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await mergeTask(
        projectId,
        task.task_id,
        `merge ${task.title}`,
      );
      const total = result.interfaces?.total_interfaces;
      setNotice(
        `已合并 ${task.task_id}；接口注册表已刷新${
          total !== undefined ? `（当前 ${total} 个接口）` : ""
        }`,
      );
      await load(true);
    } catch (mergeError) {
      setError(errorMessage(mergeError));
    } finally {
      setBusy(false);
    }
  };

  const pending = requests.filter((row) => row.status === "pending");

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">队长工作台</p>
          <h1>大纲、成员与任务分配</h1>
          <p className="page-head__desc">
            粘贴或上传 Markdown 大纲生成任务；批准成员加入后，把 A/B/C
            角色任务分配给具体成员。
          </p>
        </div>
      </header>

      {notice ? (
        <p className="inline-notice" role="status">
          {notice}
        </p>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}

      <div className="team-grid">
        <div className="panel">
          <div className="panel__head">
            <p className="eyebrow">项目大纲</p>
          </div>
          <form className="auth-form" onSubmit={handlePlan}>
            <label>
              粘贴 Markdown 大纲
              <textarea
                value={outline}
                onChange={(event) => setOutline(event.target.value)}
                placeholder="# 在线商城&#10;- 用户管理&#10;- 商品管理&#10;- 订单管理"
                required
              />
            </label>
            <label>
              上传 .md 文件
              <input
                ref={fileRef}
                type="file"
                accept=".md,.markdown,.txt"
                onChange={(event) => void handleFile(event)}
              />
            </label>
            <label>
              占位角色（逗号分隔）
              <input
                value={roles}
                onChange={(event) => setRoles(event.target.value)}
                placeholder="A,B,C"
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? "生成中" : "生成任务"}
            </button>
          </form>
        </div>

        <div className="panel">
          <div className="panel__head">
            <p className="eyebrow">加入申请</p>
            <span className="mono panel__count">{pending.length}</span>
          </div>
          {pending.length === 0 ? (
            <p className="auth-hint">暂无待审批申请。</p>
          ) : (
            <div className="team-list">
              {pending.map((row) => (
                <div className="team-row" key={row.request_id}>
                  <div>
                    <p className="team-row__name">{row.display_name}</p>
                    <p className="auth-hint mono">{row.device_id}</p>
                  </div>
                  <input
                    className="project-block__input"
                    value={areas[row.request_id] ?? ""}
                    onChange={(event) =>
                      setAreas((current) => ({
                        ...current,
                        [row.request_id]: event.target.value,
                      }))
                    }
                    placeholder="负责模块，如 user,order"
                  />
                  <div className="auth-actions">
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={busy}
                      onClick={() => void handleApprove(row)}
                    >
                      批准
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={busy}
                      onClick={() => void handleReject(row)}
                    >
                      拒绝
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel__head">
          <p className="eyebrow">成员与任务分配</p>
          <span className="mono panel__count">{tasks.length}</span>
        </div>
        {tasks.length === 0 ? (
          <p className="auth-hint">还没有任务，先用大纲生成。</p>
        ) : (
          <div className="team-list">
            {tasks.map((task) => (
              <div className="team-row" key={task.task_id}>
                <div>
                  <p className="team-row__name">{task.title}</p>
                  <p className="auth-hint mono">
                    {task.task_id} · 当前：{task.owner_name ?? task.owner_id}
                  </p>
                </div>
                <select
                  className="project-block__input"
                  value={task.owner_id}
                  disabled={busy}
                  onChange={(event) =>
                    void handleAssign(task.task_id, event.target.value)
                  }
                >
                  <option value={task.owner_id}>
                    {task.owner_name ?? task.owner_id}
                  </option>
                  {members
                    .filter((member) => member.user_id !== task.owner_id)
                    .map((member) => (
                      <option key={member.user_id} value={member.user_id}>
                        {member.name}（{member.role}）
                      </option>
                    ))}
                </select>
                {task.status === "completed" ? (
                  <button
                    type="button"
                    className="btn btn--tiny"
                    disabled={busy}
                    onClick={() => void handleMerge(task)}
                  >
                    合并
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
