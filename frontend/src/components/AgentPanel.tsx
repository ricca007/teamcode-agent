import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  controlTask,
  errorMessage,
  RECENT_TASK_LIMIT,
  sendTaskMessage,
  type TaskAction,
} from "../api/client";
import { useT, type TKey } from "../i18n";
import { formatClock } from "../lib/format";
import { useAppStore } from "../store/useAppStore";
import type { ConnectionState } from "../types";
import { EmptyState, ErrorBanner, LoadingPanel } from "./States";
import { StatusPill } from "./StatusPill";

const CONNECTION_TEXT: Record<ConnectionState, TKey> = {
  open: "conn.live",
  connecting: "conn.connectingShort",
  closed: "conn.closedShort",
};

export function AgentPanel() {
  const t = useT();
  const sessions = useAppStore((state) => state.sessions);
  const tasks = useAppStore((state) => state.tasks);
  const logs = useAppStore((state) => state.logs);
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const connection = useAppStore((state) => state.connection);
  const detailTaskIds = useAppStore((state) => state.detailTaskIds);
  const detailLoading = useAppStore((state) => state.detailLoading);
  const load = useAppStore((state) => state.load);
  const loadMoreSessions = useAppStore((state) => state.loadMoreSessions);

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [controlling, setControlling] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const streamRef = useRef<HTMLDivElement>(null);

  const activeSession =
    sessions.find((session) => session.session_id === activeSessionId) ??
    sessions.find((session) => session.status === "running") ??
    sessions[0] ??
    null;

  const visibleLogs = activeSession
    ? logs.filter((log) => log.session_id === activeSession.session_id)
    : logs;

  useEffect(() => {
    if (follow && streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [visibleLogs.length, follow, activeSession?.session_id]);

  const taskTitle = (taskId: string) =>
    tasks.find((task) => task.task_id === taskId)?.title ?? taskId;

  const loadedTaskIds = new Set(detailTaskIds);
  const remainingTasks = tasks.filter(
    (task) => !loadedTaskIds.has(task.task_id),
  ).length;

  const handleControl = async (action: TaskAction) => {
    if (!activeSession) {
      return;
    }
    setControlling(true);
    setNotice(null);
    try {
      await controlTask(activeSession.task_id, action);
      const labels: Record<TaskAction, TKey> = {
        pause: "agents.actionPaused",
        resume: "agents.actionResumed",
        terminate: "agents.actionTerminated",
      };
      setNotice(
        t("agents.controlDone", {
          title: taskTitle(activeSession.task_id),
          action: t(labels[action]),
        }),
      );
      await load();
    } catch (controlError) {
      setNotice(errorMessage(controlError));
    } finally {
      setControlling(false);
    }
  };

  const canPause =
    activeSession?.status === "running" || activeSession?.status === "pending";
  const canResume = activeSession?.status === "paused";
  const canTerminate =
    activeSession !== null &&
    !["succeeded", "failed", "terminated"].includes(activeSession.status);

  const sessionBusy =
    activeSession !== null &&
    ["pending", "running", "paused"].includes(activeSession.status);

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = message.trim();
    if (!activeSession || !text || sessionBusy) {
      return;
    }
    setSending(true);
    setNotice(null);
    try {
      await sendTaskMessage(activeSession.task_id, text);
      setMessage("");
      setNotice(t("agents.messageSent"));
      await load(true);
    } catch (sendError) {
      setNotice(errorMessage(sendError));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{t("agents.eyebrow")}</p>
          <h1>{t("nav.agents")}</h1>
          <p className="page-head__desc">{t("agents.desc")}</p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--ghost" onClick={() => void load()}>
            {t("agents.refresh")}
          </button>
        </div>
      </header>

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} />
      ) : null}

      {loading && sessions.length === 0 ? (
        <div className="panel">
          <LoadingPanel label={t("agents.loading")} />
        </div>
      ) : (
        <div className="split split--agent">
          <div className="panel">
            <div className="panel__head">
              <p className="eyebrow">{t("agents.activeSessions")}</p>
              <span className="mono panel__count">{sessions.length}</span>
            </div>
            {sessions.length === 0 ? (
              <EmptyState
                title={t("agents.emptyTitle")}
                description={t("agents.emptyDesc")}
              />
            ) : (
              <div className="session-list">
                {sessions.map((session) => {
                  const isActive =
                    activeSession?.session_id === session.session_id;
                  return (
                    <button
                      key={session.session_id}
                      type="button"
                      className={`session-row${isActive ? " is-active" : ""}`}
                      aria-pressed={isActive}
                      onClick={() => setActiveSessionId(session.session_id)}
                    >
                      <span className="session-row__top">
                        <span className="session-row__task">
                          {taskTitle(session.task_id)}
                        </span>
                        <StatusPill status={session.status} />
                      </span>
                      <span className="session-row__meta">
                        <span className="mono">{session.adapter}</span>
                        <span className="mono">{session.session_id}</span>
                      </span>
                      <span
                        className="session-row__workspace mono"
                        title={session.workspace}
                      >
                        {session.workspace}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            <div className="panel__foot">
              <p className="panel__hint">
                {t("agents.recentHint", { limit: RECENT_TASK_LIMIT })}
              </p>
              <button
                type="button"
                className="btn btn--ghost btn--tiny"
                disabled={detailLoading || remainingTasks === 0}
                onClick={() => void loadMoreSessions()}
              >
                {detailLoading ? t("common.loading") : t("agents.loadMore")}
              </button>
            </div>
          </div>

          <div className="panel log-panel">
            <header className="log-panel__head">
              <div>
                <p className="eyebrow">{t("agents.sessionLogs")}</p>
                <p className="log-panel__title">
                  {activeSession
                    ? taskTitle(activeSession.task_id)
                    : t("agents.allSessions")}
                </p>
                {activeSession ? (
                  <div className="session-actions">
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canPause}
                      onClick={() => void handleControl("pause")}
                    >
                      {t("agents.pause")}
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canResume}
                      onClick={() => void handleControl("resume")}
                    >
                      {t("agents.resume")}
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canTerminate}
                      onClick={() => void handleControl("terminate")}
                    >
                      {t("agents.terminate")}
                    </button>
                  </div>
                ) : null}
              </div>
              <div className="log-panel__tools">
                <span className={`conn conn--${connection}`}>
                  <span className="conn__dot" aria-hidden="true" />
                  {t(CONNECTION_TEXT[connection])}
                </span>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={follow}
                    onChange={(event) => setFollow(event.target.checked)}
                  />
                  {t("agents.autoScroll")}
                </label>
              </div>
            </header>

            {notice ? (
              <p className="inline-notice" role="status">
                {notice}
              </p>
            ) : null}

            {visibleLogs.length === 0 ? (
              <EmptyState
                title={t("agents.noLogsTitle")}
                description={t("agents.noLogsDesc")}
              />
            ) : (
              <div
                className="log-stream"
                ref={streamRef}
                role="log"
                aria-live="polite"
                aria-label={t("agents.liveLogs")}
              >
                {visibleLogs.map((log) => (
                  <div
                    key={log.id}
                    className={`log-line log-line--${log.level}`}
                  >
                    <time className="log-line__time mono" dateTime={log.ts}>
                      {formatClock(log.ts)}
                    </time>
                    <span className="log-line__level mono">
                      {log.level.toUpperCase()}
                    </span>
                    <span className="log-line__message">{log.message}</span>
                  </div>
                ))}
              </div>
            )}

            {activeSession ? (
              <form className="chat-form" onSubmit={handleSend}>
                <input
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder={
                    sessionBusy
                      ? t("agents.chatBusy")
                      : t("agents.chatPlaceholder")
                  }
                  disabled={sessionBusy || sending}
                  aria-label={t("agents.chatAria")}
                />
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={sessionBusy || sending || !message.trim()}
                >
                  {sending ? t("agents.sending") : t("agents.send")}
                </button>
              </form>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
