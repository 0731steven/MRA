import { Component, useMemo } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
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

export function markdownHeadingId(text: string): string {
  const normalized = text.trim().toLowerCase().replace(/[`*_~]/g, "").replace(/\s+/g, "-");
  return `section-${normalized.replace(/[^\p{L}\p{N}-]/gu, "") || "content"}`;
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
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore", output: "htmlAndMathml" }]]}
      components={{
        h1: ({ children: heading }) => <h1 id={markdownHeadingId(String(heading))}>{heading}</h1>,
        h2: ({ children: heading }) => <h2 id={markdownHeadingId(String(heading))}>{heading}</h2>,
        h3: ({ children: heading }) => <h3 id={markdownHeadingId(String(heading))}>{heading}</h3>,
        table: ({ children: tableContent }) => <div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="表格，可横向滚动"><table>{tableContent}</table></div>,
      }}
    >
      {normalized}
    </ReactMarkdown>
  </MathRenderBoundary>;
}
