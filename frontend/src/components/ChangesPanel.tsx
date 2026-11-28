import { useState } from "react";

import { useLocale, useT } from "../i18n";
import { diffStats, formatDateTime, shortHash } from "../lib/format";
import { useAppStore } from "../store/useAppStore";
import type { ChangeSet } from "../types";
import { EmptyState, ErrorBanner, LoadingPanel } from "./States";

type DiffTone = "add" | "del" | "hunk" | "meta" | "ctx";

function toneFor(line: string): DiffTone {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "meta";
  }
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("+")) {
    return "add";
  }
  if (line.startsWith("-")) {
    return "del";
  }
  return "ctx";
}

function ChangeCard({
  change,
  taskTitle,
}: {
  change: ChangeSet;
  taskTitle: string;
}) {
  const t = useT();
  const locale = useLocale();
  const [expanded, setExpanded] = useState(false);
  const stats = diffStats(change.diff);
  const lines = change.diff.split("\n");
  const collapsedLimit = 14;
  const visibleLines = expanded ? lines : lines.slice(0, collapsedLimit);
  const canExpand = lines.length > collapsedLimit;

  return (
    <article className="change-card">
      <header className="change-card__head">
        <div>
          <p className="eyebrow">
            {taskTitle} · {change.task_id}
          </p>
          <p className="change-card__commit mono">
            {shortHash(change.commit_hash, locale)}
          </p>
        </div>
        <div className="change-card__stats mono">
          <span className="diff-add">+{stats.additions}</span>
          <span className="diff-del">−{stats.deletions}</span>
          <time dateTime={change.ts}>
            {formatDateTime(change.ts, locale)}
          </time>
        </div>
      </header>

      <ul className="file-list">
        {change.files.map((file) => (
          <li key={file} className="mono">
            {file}
          </li>
        ))}
      </ul>

      <pre
        className="diff"
        aria-label={t("changes.diffAria", { task: change.task_id })}
      >
        <code>
          {visibleLines.map((line, index) => (
            <span
              key={`${change.id}-${index}`}
              className={`diff__line diff__line--${toneFor(line)}`}
            >
              {line || " "}
            </span>
          ))}
        </code>
      </pre>

      {canExpand ? (
        <div>
          <button
            type="button"
            className="btn btn--tiny"
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded
              ? t("changes.collapse")
              : t("changes.expand", { lines: lines.length })}
          </button>
        </div>
      ) : null}
    </article>
  );
}

export function ChangesPanel() {
  const t = useT();
  const changes = useAppStore((state) => state.changes);
  const tasks = useAppStore((state) => state.tasks);
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const load = useAppStore((state) => state.load);

  const totalFiles = new Set(changes.flatMap((change) => change.files)).size;
  const taskTitle = (taskId: string) =>
    tasks.find((task) => task.task_id === taskId)?.title ?? taskId;

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{t("changes.eyebrow")}</p>
          <h1>{t("nav.changes")}</h1>
          <p className="page-head__desc">
            {t("changes.desc", {
              changes: changes.length,
              files: totalFiles,
            })}
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--ghost" onClick={() => void load()}>
            {t("changes.refresh")}
          </button>
        </div>
      </header>

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} />
      ) : null}

      {loading && changes.length === 0 ? (
        <div className="panel">
          <LoadingPanel label={t("changes.loading")} />
        </div>
      ) : changes.length === 0 ? (
        <div className="panel">
          <EmptyState
            title={t("changes.emptyTitle")}
            description={t("changes.emptyDesc")}
          />
        </div>
      ) : (
        <div className="change-list">
          {changes.map((change) => (
            <ChangeCard
              key={change.id}
              change={change}
              taskTitle={taskTitle(change.task_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
