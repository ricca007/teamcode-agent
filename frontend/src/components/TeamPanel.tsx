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
import { useLocale, useT } from "../i18n";
import { useAppStore } from "../store/useAppStore";
import type { Task } from "../types";
import { ErrorBanner } from "./States";

export function TeamPanel() {
  const t = useT();
  const locale = useLocale();
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
    setNotice(t("team.outlineLoaded", { file: file.name }));
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
      await submitRequirements(projectId, outline, roleList, "plan", locale);
      setNotice(t("team.generated"));
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
      setNotice(t("team.approved", { name: row.display_name }));
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
      setNotice(t("team.rejected", { name: row.display_name }));
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
      setNotice(t("team.reassigned"));
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
        total !== undefined
          ? t("team.mergedWithCount", { task: task.task_id, total })
          : t("team.merged", { task: task.task_id }),
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
          <p className="eyebrow">{t("team.eyebrow")}</p>
          <h1>{t("team.title")}</h1>
          <p className="page-head__desc">{t("team.desc")}</p>
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
            <p className="eyebrow">{t("team.outline")}</p>
          </div>
          <form className="auth-form" onSubmit={handlePlan}>
            <label>
              {t("team.pasteOutline")}
              <textarea
                value={outline}
                onChange={(event) => setOutline(event.target.value)}
                placeholder={t("team.outlinePlaceholder")}
                required
              />
            </label>
            <label>
              {t("team.uploadFile")}
              <input
                ref={fileRef}
                type="file"
                accept=".md,.markdown,.txt"
                onChange={(event) => void handleFile(event)}
              />
            </label>
            <label>
              {t("team.roles")}
              <input
                value={roles}
                onChange={(event) => setRoles(event.target.value)}
                placeholder="A,B,C"
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? t("team.generating") : t("team.generate")}
            </button>
          </form>
        </div>

        <div className="panel">
          <div className="panel__head">
            <p className="eyebrow">{t("team.joinRequests")}</p>
            <span className="mono panel__count">{pending.length}</span>
          </div>
          {pending.length === 0 ? (
            <p className="auth-hint">{t("team.noRequests")}</p>
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
                    placeholder={t("team.areasPlaceholder")}
                  />
                  <div className="auth-actions">
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={busy}
                      onClick={() => void handleApprove(row)}
                    >
                      {t("team.approve")}
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={busy}
                      onClick={() => void handleReject(row)}
                    >
                      {t("team.reject")}
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
          <p className="eyebrow">{t("team.members")}</p>
          <span className="mono panel__count">{tasks.length}</span>
        </div>
        {tasks.length === 0 ? (
          <p className="auth-hint">{t("team.noTasks")}</p>
        ) : (
          <div className="team-list">
            {tasks.map((task) => (
              <div className="team-row" key={task.task_id}>
                <div>
                  <p className="team-row__name">{task.title}</p>
                  <p className="auth-hint mono">
                    {task.task_id} ·{" "}
                    {t("team.current", {
                      owner: task.owner_name ?? task.owner_id,
                    })}
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
                        {t("shell.teamOption", {
                          name: member.name,
                          role:
                            member.role === "owner"
                              ? t("role.leader")
                              : t("role.member"),
                        })}
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
                    {t("team.merge")}
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
