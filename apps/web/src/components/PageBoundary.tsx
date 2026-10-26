import { Component, type ReactNode } from 'react';

/** Keep the owner controls mounted even when a management page cannot render. */
export default class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <section className="panel form-panel" role="alert">
          <h2>此页面暂时无法显示</h2>
          <p className="muted spaced">
            底部接管控制仍可使用。请重新打开页面，或查看服务日志中的脱敏错误。
          </p>
          <button
            className="button secondary spaced"
            onClick={() => this.setState({ failed: false })}
          >
            重新显示页面
          </button>
        </section>
      );
    return this.props.children;
  }
}
