import { Component, type ReactNode } from "react";
import { Button, Result } from "antd";

interface Props { children: ReactNode }
interface State { failed: boolean }

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <Result status="error" title="页面暂时无法显示" subTitle="你的数据没有丢失。请刷新页面重试；如果问题持续出现，请联系课程管理员。" extra={<Button type="primary" onClick={() => window.location.reload()}>刷新页面</Button>} />;
    }
    return this.props.children;
  }
}
