import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  controlTask,
  errorMessage,
  sendTaskMessage,
  type TaskAction,
} from "../api/client";
import { formatClock } from "../lib/format";
import { useAppStore } from "../store/useAppStore";
import type { ConnectionState } from "../types";
import { EmptyState, ErrorBanner, LoadingPanel } from "./States";
import { StatusPill } from "./StatusPill";

const CONNECTION_TEXT: Record<ConnectionState, string> = {
  open: "实时推送",
  connecting: "连接中",
  closed: "已断开",
};

export function AgentPanel() {
  const sessions = useAppStore((state) => state.sessions);
  const tasks = useAppStore((state) => state.tasks);
  const logs = useAppStore((state) => state.logs);
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const connection = useAppStore((state) => state.connection);
  const load = useAppStore((state) => state.load);

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

  const handleControl = async (action: TaskAction) => {
    if (!activeSession) {
      return;
    }
    setControlling(true);
    setNotice(null);
    try {
      await controlTask(activeSession.task_id, action);
      const labels: Record<TaskAction, string> = {
        pause: "已暂停",
        resume: "已恢复",
        terminate: "已终止",
      };
      setNotice(`${taskTitle(activeSession.task_id)} ${labels[action]}`);
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
      setNotice("消息已发送，Agent 输出会实时出现在日志里");
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
          <p className="eyebrow">运行时</p>
          <h1>Agent 会话</h1>
          <p className="page-head__desc">
            每个任务在独立 Worktree 中运行一个 Coding Agent 会话，日志按会话实时推送。
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--ghost" onClick={() => void load()}>
            刷新状态
          </button>
        </div>
      </header>

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} />
      ) : null}

      {loading && sessions.length === 0 ? (
        <div className="panel">
          <LoadingPanel label="正在加载会话与日志" />
        </div>
      ) : (
        <div className="split split--agent">
          <div className="panel">
            <div className="panel__head">
              <p className="eyebrow">活跃会话</p>
              <span className="mono panel__count">{sessions.length}</span>
            </div>
            {sessions.length === 0 ? (
              <EmptyState
                title="暂无 Agent 会话"
                description="在任务看板中启动任务后，这里会显示每个会话的工作区与状态。"
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
          </div>

          <div className="panel log-panel">
            <header className="log-panel__head">
              <div>
                <p className="eyebrow">会话日志</p>
                <p className="log-panel__title">
                  {activeSession ? taskTitle(activeSession.task_id) : "全部会话"}
                </p>
                {activeSession ? (
                  <div className="session-actions">
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canPause}
                      onClick={() => void handleControl("pause")}
                    >
                      暂停
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canResume}
                      onClick={() => void handleControl("resume")}
                    >
                      恢复
                    </button>
                    <button
                      type="button"
                      className="btn btn--tiny"
                      disabled={controlling || !canTerminate}
                      onClick={() => void handleControl("terminate")}
                    >
                      终止
                    </button>
                  </div>
                ) : null}
              </div>
              <div className="log-panel__tools">
                <span className={`conn conn--${connection}`}>
                  <span className="conn__dot" aria-hidden="true" />
                  {CONNECTION_TEXT[connection]}
                </span>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={follow}
                    onChange={(event) => setFollow(event.target.checked)}
                  />
                  自动滚动
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
                title="这个会话还没有日志"
                description="Agent 启动后，stdout 与 stderr 会按时间顺序显示在这里。"
              />
            ) : (
              <div
                className="log-stream"
                ref={streamRef}
                role="log"
                aria-live="polite"
                aria-label="Agent 实时日志"
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
                      ? "Agent 正在执行，完成后可继续对话"
                      : "继续让 Agent 修改代码，例如：把 create 改成异步"
                  }
                  disabled={sessionBusy || sending}
                  aria-label="发送给 Agent 的消息"
                />
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={sessionBusy || sending || !message.trim()}
                >
                  {sending ? "发送中" : "发送"}
                </button>
              </form>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
