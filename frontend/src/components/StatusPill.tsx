import { STATUS_KEY, useT } from "../i18n";
import type { AgentStatus, TaskStatus } from "../types";

export function StatusPill({
  status,
}: {
  status: TaskStatus | AgentStatus;
}) {
  const t = useT();
  return (
    <span className={`pill pill--${status}`}>
      <span className="pill__dot" aria-hidden="true" />
      {t(STATUS_KEY[status])}
    </span>
  );
}
