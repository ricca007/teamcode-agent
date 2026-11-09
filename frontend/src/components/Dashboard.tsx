import { useState } from "react";

import { errorMessage, runTask } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { Task, TaskStatus } from "../types";
import { EmptyState, ErrorBanner } from "./States";
import { StatusPill } from "./StatusPill";

const STATUS_COLUMNS: Array<{ key: string; label: string; statuses: TaskStatus[] }> = [
  { key: "pending", label: "待处理", statuses: ["planned"] },
  { key: "active", label: "进行中", statuses: ["in_progress"] },
  { key: "attention", label: "需处理", statuses: ["blocked", "cancelled"] },
  { key: "done", label: "已交付", statuses: ["completed"] },
];

/** 成员列内按紧急程度排序，而不是按任务 ID。 */
const STATUS_ORDER: Record<TaskStatus, number> = {
  in_progress: 0,
  blocked: 1,
  planned: 2,
  completed: 3,
  cancelled: 4,
};

type GroupMode = "member" | "status";

interface MemberSummary {
  ownerId: string;
  name: string;
  tasks: Task[];
  total: number;
  done: number;
  running: number;
  pending: number;
  attention: number;
  percent: number;
}

interface BoardColumn {
  key: string;
  label: string;
  meta: string;
  items: Task[];
}

function summarizeMembers(tasks: Task[]): MemberSummary[] {
  const members = new Map<string, MemberSummary>();

  for (const task of tasks) {
    const ownerId = task.owner_id || "unassigned";
    let member = members.get(ownerId);
    if (!member) {
      member = {
        ownerId,
        name: task.owner_name ?? task.owner_id ?? "未分配",
        tasks: [],
        total: 0,
        done: 0,
        running: 0,
        pending: 0,
        attention: 0,
        percent: 0,
      };
      members.set(ownerId, member);
    }

    member.tasks.push(task);
    member.total += 1;
    if (task.status === "completed") {
      member.done += 1;
    }
    if (task.status === "in_progress") {
      member.running += 1;
    }
    if (task.status === "planned") {
      member.pending += 1;
    }
    if (task.status === "blocked" || task.status === "cancelled") {
      member.attention += 1;
    }
  }

  for (const member of members.values()) {
    member.percent =
      member.total === 0 ? 0 : Math.round((member.done / member.total) * 100);
    member.tasks.sort(
      (left, right) =>
        STATUS_ORDER[left.status] - STATUS_ORDER[right.status] ||
        left.priority - right.priority,
    );
  }

  return [...members.values()];
}

function TaskCard({
  task,
  onRun,
  running,
}: {
  task: Task;
  onRun: (task: Task) => void;
  running: boolean;
}) {
  const pathLabel = task.allowed_paths[0] ?? "未限制路径";
  const extraPaths = Math.max(task.allowed_paths.length - 1, 0);
  const canRun = task.status === "planned" || task.status === "blocked";

  return (
    <article className="task-card">
      <div className="task-card__top">
        <span className="task-card__priority mono">P{task.priority}</span>
        {task.replan_version > 1 ? (
          <span className="chip chip--replan">重规划 v{task.replan_version}</span>
        ) : null}
        <span className="task-card__status">
          <StatusPill status={task.status} />
        </span>
        {canRun ? (
          <button
            type="button"
            className="btn btn--tiny"
            disabled={running}
            onClick={() => onRun(task)}
          >
            {running ? "启动中" : "运行"}
          </button>
        ) : null}
      </div>

      <h3 className="task-card__title">{task.title}</h3>
      <p className="task-card__desc">{task.description}</p>

      <div className="task-card__meta">
        <span className="owner">
          <span className="owner__dot" aria-hidden="true" />
          {task.owner_name ?? task.owner_id}
        </span>
        <span
          className="mono task-card__path"
          title={task.allowed_paths.join(", ")}
        >
          {pathLabel}
          {extraPaths > 0 ? ` +${extraPaths}` : ""}
        </span>
      </div>

      {task.depends_on.length > 0 ? (
        <div className="task-card__deps">
          <span className="eyebrow">依赖</span>
          {task.depends_on.map((taskId) => (
            <span key={taskId} className="chip mono">
              {taskId}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function MemberCard({ member }: { member: MemberSummary }) {
  const initial = member.name.trim().charAt(0) || "?";
  return (
    <article className="member-card">
      <div className="member-card__top">
        <span className="member-avatar" aria-hidden="true">
          {initial}
        </span>
        <div>
          <p className="member-card__name">{member.name}</p>
          <p className="member-card__meta mono">
            {member.done} / {member.total} 完成 · {member.percent}%
          </p>
        </div>
      </div>

      <div
        className={`progress progress--thin${member.percent === 100 ? " is-complete" : ""}`}
        role="progressbar"
        aria-label={`${member.name}的任务完成度`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={member.percent}
      >
        <span className="progress__fill" style={{ width: `${member.percent}%` }} />
      </div>

      <div className="member-card__stats">
        <span className="member-stat member-stat--running">
          运行中 {member.running}
        </span>
        <span className="member-stat member-stat--pending">
          待处理 {member.pending}
        </span>
        <span className="member-stat member-stat--attention">
          异常 {member.attention}
        </span>
      </div>
    </article>
  );
}

function LoadingColumns() {
  return (
    <div className="kanban" aria-hidden="true">
      {STATUS_COLUMNS.map((column) => (
        <div key={column.key} className="kanban__column">
          <div className="kanban__head">
            <span className="skeleton__line" style={{ width: 56, height: 12 }} />
            <span className="skeleton__line" style={{ width: 18, height: 12 }} />
          </div>
          <div className="kanban__body">
            {[0, 1].map((index) => (
              <div key={index} className="task-card">
                <span className="skeleton__line skeleton__line--title" />
                <span className="skeleton__line" />
                <span className="skeleton__line" style={{ width: "68%" }} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Dashboard({ onOpenAgents }: { onOpenAgents: () => void }) {
  const tasks = useAppStore((state) => state.tasks);
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const load = useAppStore((state) => state.load);
  const selectedAgent = useAppStore((state) => state.selectedAgent);
  const agents = useAppStore((state) => state.agents);

  const [groupMode, setGroupMode] = useState<GroupMode>("member");
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const handleRun = async (task: Task) => {
    const agent = agents.find((item) => item.name === selectedAgent);
    if (!agent?.available) {
      setNotice(
        `${selectedAgent} 当前不可用：请先安装对应 CLI，或在顶部切换一个可用的 Agent`,
      );
      return;
    }
    setRunningTaskId(task.task_id);
    setNotice(null);
    try {
      await runTask(task.task_id, selectedAgent);
      setNotice(
        `任务「${task.title}」已用 ${selectedAgent} 启动，日志和状态会自动刷新；可在「Agent 会话」继续追问。`,
      );
      await load(true);
    } catch (runError) {
      setNotice(errorMessage(runError));
    } finally {
      setRunningTaskId(null);
    }
  };

  const total = tasks.length;
  const done = tasks.filter((task) => task.status === "completed").length;
  const running = tasks.filter(
    (task) => task.status === "in_progress",
  ).length;
  const pending = tasks.filter((task) => task.status === "planned").length;
  const attention = tasks.filter(
    (task) => task.status === "blocked" || task.status === "cancelled",
  ).length;
  const percent = total === 0 ? 0 : Math.round((done / total) * 100);

  const members = summarizeMembers(tasks);

  const columns: BoardColumn[] =
    groupMode === "member"
      ? members.map((member) => ({
          key: `member-${member.ownerId}`,
          label: member.name,
          meta: `${member.done}/${member.total} 完成`,
          items: member.tasks,
        }))
      : STATUS_COLUMNS.map((column) => {
          const items = tasks.filter((task) =>
            column.statuses.includes(task.status),
          );
          return {
            key: column.key,
            label: column.label,
            meta: `${items.length} 个`,
            items,
          };
        });

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">项目进度</p>
          <h1>任务看板</h1>
          <p className="page-head__desc">
            任务按负责人拆解，进度以成员为单位汇总，状态随成员会话和代码变更实时更新。
            本地未配置真实 Coding Agent 时，点击「运行」使用 Mock 适配器模拟执行。
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--ghost" onClick={onOpenAgents}>
            查看 Agent 会话
          </button>
        </div>
      </header>

      {notice ? (
        <p className="inline-notice" role="status">
          {notice}
        </p>
      ) : null}

      <div className="summary-strip">
        <div className="summary-strip__main">
          <div className="summary-strip__numbers">
            <strong className="summary-strip__value">{done}</strong>
            <span className="summary-strip__total">/ {total} 个任务完成</span>
          </div>
          <div
            className="progress"
            role="progressbar"
            aria-label="项目整体任务完成度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <span className="progress__fill" style={{ width: `${percent}%` }} />
          </div>
        </div>
        <dl className="summary-strip__meta">
          <div>
            <dt>进行中</dt>
            <dd className="mono">{running}</dd>
          </div>
          <div>
            <dt>待处理</dt>
            <dd className="mono">{pending}</dd>
          </div>
          <div>
            <dt>需处理</dt>
            <dd className="mono">{attention}</dd>
          </div>
        </dl>
      </div>

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} />
      ) : null}

      {loading && tasks.length === 0 ? (
        <LoadingColumns />
      ) : total === 0 ? (
        <div className="panel">
          <EmptyState
            title="还没有开发任务"
            description="输入项目需求后，Manager Agent 会生成任务、依赖和接口契约。"
            action={
              <button type="button" className="btn" onClick={() => void load()}>
                重新加载
              </button>
            }
          />
        </div>
      ) : (
        <>
          <section aria-labelledby="member-progress-title">
            <div className="section-head">
              <h2 id="member-progress-title" className="section-head__title">
                成员进度
              </h2>
              <span className="section-head__meta">按负责人汇总</span>
            </div>
            <div className="member-progress">
              {members.map((member) => (
                <MemberCard key={member.ownerId} member={member} />
              ))}
            </div>
          </section>

          <div className="board">
            <div className="board-head">
              <p className="eyebrow">开发任务</p>
              <div
                className="segmented segmented--sm"
                role="group"
                aria-label="任务分组方式"
              >
                <button
                  type="button"
                  aria-pressed={groupMode === "member"}
                  onClick={() => setGroupMode("member")}
                >
                  按成员
                </button>
                <button
                  type="button"
                  aria-pressed={groupMode === "status"}
                  onClick={() => setGroupMode("status")}
                >
                  按状态
                </button>
              </div>
            </div>

            <div className="kanban">
              {columns.map((column) => (
                <section
                  key={column.key}
                  className="kanban__column"
                  aria-labelledby={`kanban-${column.key}`}
                >
                  <header className="kanban__head">
                    <h3
                      id={`kanban-${column.key}`}
                      className="kanban__title"
                    >
                      {column.label}
                    </h3>
                    <span className="kanban__count mono">{column.meta}</span>
                  </header>
                  <div className="kanban__body">
                    {column.items.length === 0 ? (
                      <p className="kanban__empty">暂无任务</p>
                    ) : (
                      column.items.map((task) => (
                        <TaskCard
                          key={task.task_id}
                          task={task}
                          onRun={handleRun}
                          running={runningTaskId === task.task_id}
                        />
                      ))
                    )}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
