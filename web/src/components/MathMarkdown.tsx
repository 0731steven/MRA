import { Component, useMemo } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { normalizeMathMarkdown } from "@/utils/mathMarkdown";

interface MathMarkdownProps {
  children: string;
}

interface BoundaryProps {
  source: string;
  children: ReactNode;
}

interface BoundaryState {
  failed: boolean;
}

class MathRenderBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  componentDidUpdate(previous: BoundaryProps) {
    if (this.state.failed && previous.source !== this.props.source) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return <span className="math-render-fallback" role="note">{this.props.source}</span>;
    }
    return this.props.children;
  }
}

/** One resilient Markdown + KaTeX entry point for all learning content. */
export function MathMarkdown({ children }: MathMarkdownProps) {
  const normalized = useMemo(() => normalizeMathMarkdown(children), [children]);
  return <MathRenderBoundary source={children}>
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore", output: "htmlAndMathml" }]]}
    >
      {normalized}
    </ReactMarkdown>
  </MathRenderBoundary>;
}
