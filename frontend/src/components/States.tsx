import type { ReactNode } from "react";

export function SkeletonLines({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      <span className="skeleton__line skeleton__line--title" />
      {Array.from({ length: rows }, (_, index) => (
        <span
          key={index}
          className="skeleton__line"
          style={{ width: `${92 - index * 9}%` }}
        />
      ))}
    </div>
  );
}

export function LoadingPanel({ label = "正在加载数据" }: { label?: string }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <SkeletonLines rows={5} />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <svg
        className="empty__icon"
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M8 4 4 12l4 8M16 4l4 8-4 8" />
      </svg>
      <p className="empty__title">{title}</p>
      <p className="empty__desc">{description}</p>
      {action}
    </div>
  );
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-banner" role="alert">
      <div>
        <p className="error-banner__title">部分请求没有成功</p>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" className="btn btn--tiny" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}
