import { Component, type ErrorInfo, type ReactNode } from "react";

import { translate } from "../i18n";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 页面级错误边界：单个视图渲染失败时只降级该视图，
 * 记录到浏览器控制台并给出重试入口，避免整页白屏。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[TeamCode] 页面渲染失败", error, info.componentStack);
  }

  private handleReload = (): void => {
    this.setState({ error: null });
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="panel">
          <div className="empty" role="alert">
            <p className="empty__title">{translate("errors.pageTitle")}</p>
            <p className="empty__desc">
              {translate("errors.pageDesc", {
                message:
                  this.state.error.message || translate("errors.unknown"),
              })}
            </p>
            <button type="button" className="btn btn--tiny" onClick={this.handleReload}>
              {translate("common.reload")}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
