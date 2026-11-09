import { STATUS_LABEL } from "../lib/format";
import type { AgentStatus, TaskStatus } from "../types";

export function StatusPill({
  status,
}: {
  status: TaskStatus | AgentStatus;
}) {
  return (
    <span className={`pill pill--${status}`}>
      <span className="pill__dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}
