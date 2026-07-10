import { useEffect, useState, useCallback, useRef, useImperativeHandle, forwardRef } from "react";
import { useParams } from "react-router-dom";
import { Drawer, Spin, Tooltip, message } from "antd";
import {
  MessageOutlined, CloseOutlined, SendOutlined, DeleteOutlined,
  UserOutlined, PaperClipOutlined, FileTextOutlined,
  FileImageOutlined, DownloadOutlined, GlobalOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkWikiLink from "remark-wiki-link";
import remarkFrontmatter from "remark-frontmatter";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import katex from "katex";
import { load as yamlLoad } from "js-yaml";
import { apiClient } from "@/api/client";

interface Report {
  id: number;
  summary_text: string;
  vault_path: string;
  content: string;
  created_at: string;
}

// ─── Reading progress bar ───────────────────────────────────────────────────
function ReadingProgress({ scrollContainerId }: { scrollContainerId: string }) {
  const [pct, setPct] = useState(0);
  useEffect(() => {
    const el = document.getElementById(scrollContainerId);
    if (!el) return;
    const onScroll = () => {
      const scrollable = el.scrollHeight - el.clientHeight;
      setPct(scrollable > 0 ? Math.min(100, (el.scrollTop / scrollable) * 100) : 0);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [scrollContainerId]);
  if (pct <= 0) return null;
  return <div className="reading-progress-bar" style={{ width: `${pct}%` }} aria-hidden="true" />;
}

// ─── AI avatar (premium, animated) ─────────────────────────────────────────────
function SparkleGlyph({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
      className="ai-avatar-spark" style={{ position: "relative", color: "#fff", filter: "drop-shadow(0 1px 1px rgba(0,0,0,0.15))" }}>
      <path d="M12 2.4c.45 3.85 2.05 5.45 5.9 5.9-3.85.45-5.45 2.05-5.9 5.9-.45-3.85-2.05-5.45-5.9-5.9 3.85-.45 5.45-2.05 5.9-5.9Z" fill="currentColor" />
      <path d="M18.4 13.2c.2 1.95.95 2.7 2.9 2.95-1.95.2-2.7.95-2.95 2.9-.2-1.95-.95-2.7-2.9-2.95 1.95-.25 2.7-.95 2.95-2.9Z" fill="currentColor" opacity="0.9" />
    </svg>
  );
}

function AiAvatar({ size = 32, radius = 999 }: { size?: number; radius?: number }) {
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }} aria-hidden="true">
      <div className="ai-avatar-glow" style={{ position: "absolute", inset: -4, borderRadius: radius, filter: "blur(6px)" }} />
      <div className="ai-avatar-grad" style={{ position: "relative", width: "100%", height: "100%", borderRadius: radius, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", boxShadow: "0 4px 12px rgba(124,58,237,0.35)" }}>
        <span className="ai-avatar-sheen" style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: "33%", background: "rgba(255,255,255,0.3)", filter: "blur(2px)" }} />
        <SparkleGlyph size={Math.round(size * 0.58)} />
      </div>
    </div>
  );
}

const mdClass = "report-md markdown-body";

const mdBodyStyle: React.CSSProperties = {
  boxSizing: "border-box",
  maxWidth: 960,
  margin: "0 auto",
  padding: "40px 52px",
  background: "#ffffff",
  borderRadius: 12,
  boxShadow: "0 2px 16px rgba(99,102,241,0.07), 0 1px 4px rgba(0,0,0,0.05)",
};

const P = "";

type SourceType = "paper" | "patent" | "web" | "note";

const SOURCE_TYPE_CONF: Record<SourceType, { label: string; bg: string; color: string; border: string }> = {
  paper:  { label: "论文", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
  patent: { label: "专利", bg: "#f0fdf4", color: "#15803d", border: "#bbf7d0" },
  web:    { label: "Web",  bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" },
  note:   { label: "笔记", bg: "#faf5ff", color: "#7e22ce", border: "#e9d5ff" },
};

const SOURCE_TYPE_ICON: Record<SourceType, React.ReactNode> = {
  paper:  <FileTextOutlined />,
  patent: <PaperClipOutlined />,
  web:    <GlobalOutlined />,
  note:   <FileImageOutlined />,
};

function detectSourceType(fileDir: string): SourceType {
  const d = fileDir.toLowerCase().replace(/\\/g, "/");
  if (d.includes("ieee_paper") || d.includes("paper_md") || d.includes("/papers/")) return "paper";
  if (d.includes("patent_md") || d.includes("/patents/") || (d.includes("patent") && !d.includes("paper"))) return "patent";
  if (d.includes("raw/web") || d.includes("/web/")) return "web";
  return "note";
}

const wikiLinkOptions = {
  pageResolver: (name: string) => [name],
  aliasDivider: P,
  hrefTemplate: (permalink: string) =>
    `/api/obsidian/vault/${encodeURIComponent(permalink)}.md`,
};

function splitFrontmatter(content: string): { meta: Record<string, unknown> | null; body: string } {
  const matchA = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (matchA) {
    try { return { meta: yamlLoad(matchA[1]) as Record<string, unknown>, body: matchA[2] }; }
    catch { return { meta: null, body: content }; }
  }
  const matchB = content.match(/^([\s\S]*?)\n---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (matchB) {
    try {
      const meta = yamlLoad(matchB[2]) as Record<string, unknown>;
      const before = matchB[1].trim();
      return { meta, body: before ? `${before}\n\n${matchB[3]}` : matchB[3] };
    } catch { return { meta: null, body: content }; }
  }
  return { meta: null, body: content };
}

function fixObsidianPipe(body: string): string {
  return body
    .replace(/\\\|/g, "|")
    .replace(/\[\[([^\]]+)\]\]/g, (_m, inner) => `[[${inner.replaceAll("|", P)}]]`);
}

function fixObsidianImages(body: string, fileDir: string, token: string): string {
  // Match both bare ![[...]] and backtick-wrapped `![[...]]` (LLM sometimes copies prompt examples verbatim)
  return body.replace(/`?!\[\[([^\]]+?)\]\]`?/g, (_m, inner) => {
    const path = inner.trim();
    // Multi-level paths like "dir/images/file.jpg" are vault-relative — never prepend fileDir.
    // Only bare single-component names (no "/") may be local-relative.
    const vaultPath = (fileDir && !path.startsWith("/") && !path.includes("/"))
      ? `${fileDir}/${path}`
      : path;
    const encodedPath = vaultPath.split("/").map(encodeURIComponent).join("/");
    const url = `/api/obsidian/img/${encodedPath}?token=${encodeURIComponent(token)}`;
    return `![${path.split("/").pop() ?? path}](${url})`;
  });
}

function fixChineseNumbering(body: string): string {
  return body.replace(/（(\d+)）/g, (_, n) =>
    n === "1" ? "\n\n- （1）" : "\n- （" + n + "）"
  );
}

// Strip [1], [1,2], [3] affiliation superscripts from IEEE-style author strings.
// Only keep the first line (author names); discard affiliation institution lines.
function cleanAuthorAffiliations(raw: string): string {
  const firstLine = raw.split(/\r?\n/)[0] ?? raw;
  return firstLine
    .replace(/\[\d+(?:,\s*\d+)*\]/g, "")  // remove [1], [1,2], [3,4] etc.
    .replace(/\s+,/g, ",")                  // collapse "Name , Next" → "Name, Next"
    .replace(/,\s*$/, "")                   // strip trailing comma
    .trim();
}

// Escape lone numeric reference labels [1], [2] in body text so GFM does not
// treat them as link-reference syntax when there are numbered bibliography entries.
function escapeNumericRefLinks(body: string): string {
  return body.replace(/\[(\d+)\](?!\s*:)/g, "&#91;$1&#93;");
}

// Escape standalone ~ (not ~~ or inside $...$ / $$...$$ math spans) to prevent
// GFM subscript/strikethrough mis-parsing of tilde-range notation like "26~280 nA".
function escapeSingleTildes(body: string): string {
  const mathPat = /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/g;
  const parts: string[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = mathPat.exec(body)) !== null) {
    parts.push(body.slice(last, match.index).replace(/(?<![~\\])~(?!~)/g, "\\~"));
    parts.push(match[0]); // math span verbatim
    last = match.index + match[0].length;
  }
  parts.push(body.slice(last).replace(/(?<![~\\])~(?!~)/g, "\\~"));
  return parts.join("");
}

// Convert LaTeX \(…\) / \[…\] delimiters to $…$ / $$…$$. remark-math (and the
// renderMathToHtml fallback below) only recognize $-delimiters; LLM reports emit
// \(…\), which CommonMark would otherwise unescape to bare parens, breaking the
// formula. Must run before markdown processing / tilde-escaping.
function normalizeMathDelimiters(body: string): string {
  return body
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, tex) => `$$${tex}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, tex) => `$${tex}$`);
}

// Pre-render $…$ / $$…$$ to KaTeX HTML. remark-math only sees math in markdown
// text nodes, so $…$ embedded in MinerU's raw <table> HTML (rendered via
// rehype-raw) never gets processed and shows as literal source. Rendering it to
// HTML up front works everywhere — inside HTML tables included. KaTeX '|' is
// entity-escaped so it can't be mistaken for a markdown table separator.
function renderMathToHtml(body: string): string {
  const sanitizeTex = (tex: string): string =>
    tex
      .replace(/[-� -]/g, "")
      .replace(/\\tag\{\s*\}/g, "");
  const render = (tex: string, display: boolean): string => {
    try {
      return katex
        .renderToString(sanitizeTex(tex.trim()), { displayMode: display, throwOnError: false, output: "html" })
        .replace(/\n/g, "")
        .replace(/\|/g, "&#124;");
    } catch {
      return display ? `$$${tex}$$` : `$${tex}$`;
    }
  };
  return body
    .replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => render(tex, true))
    .replace(/(?<!\\)\$([^$\n]+?)\$/g, (_m, tex) => render(tex, false));
}

function FrontmatterCard({ meta }: { meta: Record<string, unknown> }) {
  const status = String(meta.status ?? "");
  const sources = meta.sources as Record<string, number> | undefined;

  const statusCfg: Record<string, { bg: string; color: string; dot: string; label: string }> = {
    complete:     { bg: "#f0fdf4", color: "#16a34a", dot: "#22c55e", label: "完整报告" },
    insufficient: { bg: "#fff7ed", color: "#ea580c", dot: "#f97316", label: "素材不足" },
    incomplete:   { bg: "#fefce8", color: "#ca8a04", dot: "#eab308", label: "部分完成" },
  };
  const sc = statusCfg[status];

  const paperCount  = sources ? (sources.papers  ?? sources["论文"]  ?? 0) : 0;
  const patentCount = sources ? (sources.patents ?? sources["专利"]  ?? 0) : 0;
  const webCount    = sources ? (sources.web     ?? sources["Web"]   ?? 0) : 0;
  const totalSources = Number(paperCount) + Number(patentCount) + Number(webCount);

  const chipStyle = (bg: string, color: string, border: string): React.CSSProperties => ({
    display: "inline-flex", alignItems: "center", gap: 5,
    background: bg, color, border: `1px solid ${border}`,
    borderRadius: 20, padding: "3px 10px", fontSize: 12, fontWeight: 500, lineHeight: 1.5,
    whiteSpace: "nowrap",
  });

  return (
    <div style={{
      marginBottom: 28,
      padding: "14px 18px",
      background: "linear-gradient(135deg, #fafbff 0%, #f5f3ff 100%)",
      borderRadius: 10,
      border: "1px solid #e8ebf8",
      boxShadow: "0 1px 4px rgba(99,102,241,0.06)",
    }}>
      {/* Title row */}
      {meta.title != null && (
        <div style={{ fontSize: 17, fontWeight: 700, color: "#1e1b4b", marginBottom: 10, lineHeight: 1.4 }}>
          {String(meta.title)}
        </div>
      )}
      {/* Chips row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 8px", alignItems: "center" }}>
        {sc && (
          <span style={chipStyle(sc.bg, sc.color, sc.dot + "44")}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: sc.dot, display: "inline-block", flexShrink: 0 }} />
            {sc.label}
          </span>
        )}
        {meta.date != null && (
          <span style={chipStyle("#f8fafc", "#64748b", "#cbd5e1")}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            {String(meta.date)}
          </span>
        )}
        {totalSources > 0 && (
          <span style={chipStyle("#eef2ff", "#4f46e5", "#c7d2fe")}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            {paperCount > 0 && `论文 ${paperCount} 篇`}
            {paperCount > 0 && patentCount > 0 && "  ·  "}
            {patentCount > 0 && `专利 ${patentCount} 项`}
            {(paperCount > 0 || patentCount > 0) && webCount > 0 && "  ·  "}
            {webCount > 0 && `Web ${webCount} 条`}
          </span>
        )}
        {meta.domain != null && (
          <span style={chipStyle("#fff7ed", "#c2410c", "#fed7aa")}>
            {String(meta.domain)}
          </span>
        )}
        {Array.isArray(meta.tags) && (meta.tags as string[]).map((t) => (
          <span key={t} style={chipStyle("#f0f9ff", "#0369a1", "#bae6fd")}>{t}</span>
        ))}
      </div>
    </div>
  );
}


// ─── Citation Metadata Card (paper / patent / web frontmatter) ───────────────
function CitationMetaCard({ meta, sourceType }: { meta: Record<string, unknown>; sourceType: SourceType }) {
  const str = (v: unknown): string => (v == null ? "" : String(v));
  const has = (v: unknown): boolean => v != null && str(v).trim() !== "";

  // Fields by source type
  const authors  = cleanAuthorAffiliations(str(meta.authors  ?? meta.author ?? meta.inventor ?? meta["发明人"] ?? ""));
  const year     = str(meta.year     ?? meta.date ?? "").slice(0, 4);
  const venue    = str(meta.venue    ?? meta.journal ?? meta.conference ?? meta.publisher ?? meta["来源"] ?? "");
  const doi      = str(meta.doi      ?? meta.DOI ?? "");
  const patentNo = str(meta.patent_number ?? meta["申请号"] ?? meta["专利号"] ?? "");
  const ipc      = str(meta.ipc ?? meta.IPC ?? meta["IPC"] ?? "");
  const abstract = str(meta.abstract ?? meta["摘要"] ?? "");
  const core     = str(meta.core_innovation ?? meta["核心创新"] ?? "");
  const url      = str(meta.url ?? meta.link ?? "");

  const rowStyle: React.CSSProperties = {
    display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5, lineHeight: 1.55,
  };
  const labelStyle: React.CSSProperties = {
    flexShrink: 0, width: 56, color: "#9ca3af", fontWeight: 500, paddingTop: 1,
  };
  const valStyle: React.CSSProperties = { color: "#1e1b4b", wordBreak: "break-word" };

  const rows: { label: string; value: string; show: boolean }[] = [
    { label: "作者",    value: authors,  show: sourceType !== "web" && has(authors) },
    { label: "年份",    value: year,     show: has(year) },
    { label: "来源",    value: venue,    show: has(venue) },
    { label: "DOI",    value: doi,      show: sourceType === "paper" && has(doi) },
    { label: "专利号",  value: patentNo, show: sourceType === "patent" && has(patentNo) },
    { label: "IPC",    value: ipc,      show: sourceType === "patent" && has(ipc) },
    { label: "链接",    value: url,      show: sourceType === "web" && has(url) },
  ].filter(r => r.show);

  const hasAbstract = has(abstract);
  const hasCore     = has(core);

  if (rows.length === 0 && !hasAbstract && !hasCore) return null;

  return (
    <div className="citation-meta-card" style={{
      margin: "0 0 20px 0",
      borderRadius: 10,
      border: "1px solid #e8ebf8",
      background: "linear-gradient(135deg, #fafbff 0%, #f5f3ff 100%)",
      overflow: "hidden",
      boxShadow: "0 1px 4px rgba(99,102,241,0.06)",
    }}>
      {/* Colored top strip */}
      <div style={{
        height: 3,
        background: sourceType === "paper"  ? "linear-gradient(90deg,#3b82f6,#6366f1)" :
                    sourceType === "patent" ? "linear-gradient(90deg,#10b981,#34d399)" :
                    sourceType === "web"    ? "linear-gradient(90deg,#f97316,#fb923c)" :
                                              "linear-gradient(90deg,#a855f7,#c084fc)",
      }} />
      <div style={{ padding: "12px 16px" }}>
        {rows.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: (hasAbstract || hasCore) ? 12 : 0 }}>
            {rows.map(r => (
              <div key={r.label} style={rowStyle}>
                <span style={labelStyle}>{r.label}</span>
                <span style={valStyle}>
                  {r.label === "DOI"   && <a href={`https://doi.org/${r.value}`} target="_blank" rel="noopener noreferrer" style={{ color: "#4f46e5", textDecoration: "underline" }}>{r.value}</a>}
                  {r.label === "链接"  && <a href={r.value} target="_blank" rel="noopener noreferrer" style={{ color: "#4f46e5", textDecoration: "underline", wordBreak: "break-all" }}>{r.value}</a>}
                  {r.label !== "DOI" && r.label !== "链接" && r.value}
                </span>
              </div>
            ))}
          </div>
        )}
        {hasAbstract && (
          <div style={{ marginTop: rows.length > 0 ? 2 : 0 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#9ca3af", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 4 }}>摘要</div>
            <div className="citation-abstract" style={{ fontSize: 13, lineHeight: 1.7, color: "#374151", maxHeight: 110, overflow: "hidden", position: "relative" }}>
              {abstract}
              <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 32, background: "linear-gradient(transparent, #fafbff)" }} />
            </div>
          </div>
        )}
        {hasCore && (
          <div style={{ marginTop: 10, padding: "8px 12px", background: "#ede9fe", borderRadius: 7, borderLeft: "3px solid #7c3aed" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#7c3aed", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 3 }}>核心创新</div>
            <div style={{ fontSize: 12.5, color: "#3b0764", lineHeight: 1.6 }}>{core}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function MarkdownContent({ content, onWikiClick, fileDir = "" }: { content: string; onWikiClick: (name: string) => void; fileDir?: string }) {
  const token = localStorage.getItem("token") ?? "";
  const { meta, body } = splitFrontmatter(content);
  const cleanBody = escapeSingleTildes(normalizeMathDelimiters(fixChineseNumbering(fixObsidianImages(fixObsidianPipe(body), fileDir, token))));

  return (
    <div className={mdClass} style={mdBodyStyle}>
      {meta && <FrontmatterCard meta={meta} />}
      <ReactMarkdown
        remarkPlugins={[remarkFrontmatter, remarkGfm, remarkMath, [remarkWikiLink, wikiLinkOptions]]}
        rehypePlugins={[rehypeHighlight, rehypeKatex, rehypeRaw]}
        components={{
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ...(({ yaml: _yaml, ...rest }: any) => rest)({ yaml: () => null }),
          a({ href, children, ...props }) {
            if (href?.startsWith("/api/obsidian/vault/")) {
              const name = decodeURIComponent(href.replace("/api/obsidian/vault/", "").replace(/\.md$/, ""));
              return (
                <a {...props} href="#" style={{ color: "#722ed1", textDecoration: "underline", textDecorationStyle: "dotted", cursor: "pointer" }}
                  onClick={(e) => { e.preventDefault(); onWikiClick(name); }}>
                  {children}
                </a>
              );
            }
            return <a {...props} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
          img({ src, alt, ...props }) {
            if (!src) return null;
            if (src.startsWith("http://") || src.startsWith("https://") || src.startsWith("/api/") || src.startsWith("data:"))
              return <img src={src} alt={alt} {...props} style={{ maxWidth: "100%", display: "block", margin: "12px 0" }} />;
            const rel = src.replace(/^\.?\/?/, "");
            // Multi-level paths are vault-relative; bare names are local-relative (same logic as fixObsidianImages).
            const vaultPath = (fileDir && !rel.includes("/")) ? `${fileDir}/${rel}` : rel;
            const encodedPath = vaultPath.split("/").map(encodeURIComponent).join("/");
            return <img src={`/api/obsidian/img/${encodedPath}?token=${encodeURIComponent(token)}`} alt={alt} {...props} style={{ maxWidth: "100%", display: "block", margin: "12px 0" }} />;
          },
        }}
      >
        {cleanBody}
      </ReactMarkdown>
    </div>
  );
}

// ── Chat Panel ────────────────────────────────────────────────────────────────

interface ToolCall { name: string; params: string; done: boolean }
interface Attachment { name: string; type: "image" | "text"; content: string; mime?: string }
interface ChatMsg { role: "user" | "assistant"; content: string; toolCalls?: ToolCall[]; attachments?: Attachment[] }

const WELCOME_TEXT = `👋 你好！我是这份报告的 **问答助手**，可以帮你：

- 📖 **解读报告** —— 概括核心结论、拆解技术全景表与详细分析
- 🔬 **深挖文献** —— 讲清引用论文 / 专利的具体方法、指标与数据
- ⚖️ **横向对比** —— 比较不同方案的取舍、适用场景与优劣
- 📎 **结合资料** —— 基于你上传的图片或 PDF 进一步分析

直接输入问题，或点选下面的示例开始 👇`;

const WELCOME_SUGGESTIONS = [
  "用一段话总结这份报告的核心结论",
  "报告引用了哪些关键论文？各自解决了什么问题",
  "这些方案之间有哪些取舍和优劣？",
];

const ReportChatPanel = forwardRef<{ clearHistory: () => void }, { reportId: number; onClose?: () => void; inline?: boolean }>(
function ReportChatPanel({ reportId, onClose, inline }, ref) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [histLoaded, setHistLoaded] = useState(false);
  const [panelHeight, setPanelHeight] = useState(560);
  const [panelWidth, setPanelWidth] = useState(420);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);
  const dragWRef = useRef<{ startX: number; startW: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    for (const file of files) {
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          const b64 = (reader.result as string).split(",")[1];
          setAttachments(prev => [...prev, { name: file.name, type: "image", content: b64, mime: file.type }]);
        };
        reader.readAsDataURL(file);
      } else if (file.type === "application/pdf") {
        const hide = message.loading(`正在解析 ${file.name}…`, 0);
        try {
          const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
          GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.mjs", import.meta.url).toString();
          const pdf = await getDocument({ data: await file.arrayBuffer() }).promise;
          const parts: string[] = [];
          for (let i = 1; i <= pdf.numPages; i++) {
            const page = await pdf.getPage(i);
            const ct = await page.getTextContent();
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            parts.push(`--- 第 ${i} 页 ---\n${ct.items.map((x: any) => x.str ?? "").join(" ")}`);
          }
          setAttachments(prev => [...prev, { name: file.name, type: "text", content: parts.join("\n\n").slice(0, 80000) }]);
        } catch (err) { message.error(`PDF 解析失败: ${err}`); }
        finally { hide(); }
      } else {
        const text = await file.text();
        setAttachments(prev => [...prev, { name: file.name, type: "text", content: text.slice(0, 80000) }]);
      }
    }
  };

  const onDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startH: panelHeight };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPanelHeight(Math.max(200, Math.min(window.innerHeight - 80, dragRef.current.startH + dragRef.current.startY - ev.clientY)));
    };
    const onUp = () => { dragRef.current = null; window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const onDragWidthStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragWRef.current = { startX: e.clientX, startW: panelWidth };
    const onMove = (ev: MouseEvent) => {
      if (!dragWRef.current) return;
      setPanelWidth(Math.max(280, Math.min(window.innerWidth - 80, dragWRef.current.startW + dragWRef.current.startX - ev.clientX)));
    };
    const onUp = () => { dragWRef.current = null; window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  useEffect(() => {
    if ((!inline && !open) || histLoaded) return;
    apiClient.get<ChatMsg[]>(`/api/reports/${reportId}/chat/history`)
      .then(res => setMsgs(res.data))
      .catch(() => {})
      .finally(() => setHistLoaded(true));
  }, [open, inline, histLoaded, reportId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text && attachments.length === 0) return;
    if (loading) return;
    setInput("");
    const currentAttachments = [...attachments];
    setAttachments([]);
    setMsgs(prev => [...prev, { role: "user", content: text, attachments: currentAttachments.length > 0 ? currentAttachments : undefined }]);
    setLoading(true);
    setMsgs(prev => [...prev, { role: "assistant", content: "" }]);

    let fullMessage = text;
    for (const att of currentAttachments)
      if (att.type === "text") fullMessage += `\n\n【用户上传文件：${att.name}】\n\`\`\`\n${att.content}\n\`\`\``;
    const imageAtts = currentAttachments.filter(a => a.type === "image");

    abortRef.current = new AbortController();
    try {
      const token = localStorage.getItem("token") ?? "";
      const resp = await fetch(`/api/reports/${reportId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify({ message: fullMessage, extra_images: imageAtts.map(a => ({ mime: a.mime ?? "image/png", data: a.content })) }),
        signal: abortRef.current.signal,
      });
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) { setLoading(false); return; }
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.delta) {
              setMsgs(prev => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  const toolCalls = last.toolCalls?.map((tc, i, arr) => i === arr.length - 1 ? { ...tc, done: true } : tc);
                  next[next.length - 1] = { ...last, content: last.content + data.delta, toolCalls };
                }
                return next;
              });
            } else if (data.tool) {
              const params = data.tool === "list_sources" ? "（无参数）" : `stem: "${data.stem ?? ""}"`;
              setMsgs(prev => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  const updated = (last.toolCalls ?? []).map((tc, i, arr) => i === arr.length - 1 ? { ...tc, done: true } : tc);
                  next[next.length - 1] = { ...last, toolCalls: [...updated, { name: data.tool, params, done: false }] };
                }
                return next;
              });
            }
          } catch { /* ignore malformed SSE */ }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== "AbortError") message.error("对话请求失败");
    } finally { setLoading(false); }
  };

  const clearHistory = async () => {
    await apiClient.delete(`/api/reports/${reportId}/chat/history`);
    setMsgs([]);
  };

  useImperativeHandle(ref, () => ({ clearHistory }));

  const panelContent = (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "#fafbff" }}>
      {!inline && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0, padding: "12px 16px", background: "#fff", borderBottom: "1px solid #eef0f6", boxShadow: "0 1px 4px rgba(99,102,241,0.06)" }}>
          <AiAvatar size={32} radius={10} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: "#1a1a2e", lineHeight: 1.2 }}>报告问答</div>
            <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 1 }}>基于报告及引用素材</div>
          </div>
          <Tooltip title="清空对话">
            <button onClick={clearHistory} style={{ border: "none", background: "none", cursor: "pointer", color: "#c4c9d4", padding: 4, borderRadius: 6, display: "flex", alignItems: "center" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#6366f1")} onMouseLeave={e => (e.currentTarget.style.color = "#c4c9d4")}>
              <DeleteOutlined style={{ fontSize: 14 }} />
            </button>
          </Tooltip>
          <Tooltip title="关闭">
            <button onClick={() => { setOpen(false); onClose?.(); }} style={{ border: "none", background: "none", cursor: "pointer", color: "#c4c9d4", padding: 4, borderRadius: 6, display: "flex", alignItems: "center" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#ef4444")} onMouseLeave={e => (e.currentTarget.style.color = "#c4c9d4")}>
              <CloseOutlined style={{ fontSize: 14 }} />
            </button>
          </Tooltip>
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "16px 14px", display: "flex", flexDirection: "column", gap: 16, minHeight: 0 }}>
        {!histLoaded && <div style={{ display: "flex", justifyContent: "center", paddingTop: 40 }}><Spin size="small" /></div>}
        {histLoaded && msgs.length === 0 && (
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <AiAvatar size={30} radius={10} />
            <div style={{ maxWidth: "82%", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ background: "#fff", color: "#1f2937", borderRadius: "4px 16px 16px 16px", padding: "10px 14px", fontSize: 13.5, lineHeight: 1.65, boxShadow: "0 1px 4px rgba(0,0,0,0.07)", border: "1px solid #f0f0f8" }}>
                <div className="chat-md markdown-body" style={{ fontSize: 13.5, background: "transparent", lineHeight: 1.7 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeHighlight, rehypeKatex]}>{WELCOME_TEXT}</ReactMarkdown>
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                {WELCOME_SUGGESTIONS.map((s, i) => (
                  <button key={i} onClick={() => send(s)} disabled={loading}
                    style={{ textAlign: "left", background: "#f5f6ff", border: "1px solid #e0e3f8", color: "#4f46e5", borderRadius: 10, padding: "7px 12px", fontSize: 12.5, lineHeight: 1.4, cursor: loading ? "not-allowed" : "pointer", transition: "all 0.15s" }}
                    onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = "#eef2ff"; e.currentTarget.style.borderColor = "#c7d2fe"; } }}
                    onMouseLeave={e => { e.currentTarget.style.background = "#f5f6ff"; e.currentTarget.style.borderColor = "#e0e3f8"; }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", flexDirection: m.role === "user" ? "row-reverse" : "row" }}>
            {m.role === "user" ? (
              <div style={{ width: 30, height: 30, borderRadius: 10, flexShrink: 0, background: "linear-gradient(135deg,#10b981,#059669)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 2px 6px rgba(0,0,0,0.12)" }}>
                <UserOutlined style={{ color: "#fff", fontSize: 13 }} />
              </div>
            ) : (
              <AiAvatar size={30} radius={10} />
            )}
            <div style={{ maxWidth: "82%", display: "flex", flexDirection: "column", gap: 4, alignItems: m.role === "user" ? "flex-end" : "flex-start" }}>
              {m.role === "user" && m.attachments && m.attachments.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "flex-end" }}>
                  {m.attachments.map((att, j) => att.type === "image"
                    ? <img key={j} src={`data:${att.mime};base64,${att.content}`} alt={att.name} style={{ maxWidth: 160, maxHeight: 120, borderRadius: 8, boxShadow: "0 1px 6px rgba(0,0,0,0.15)" }} />
                    : <div key={j} style={{ display: "flex", alignItems: "center", gap: 5, background: "rgba(255,255,255,0.2)", borderRadius: 8, padding: "4px 10px", fontSize: 12, color: "#fff", border: "1px solid rgba(255,255,255,0.3)" }}><FileTextOutlined style={{ fontSize: 13 }} /><span>{att.name}</span></div>
                  )}
                </div>
              )}
              {m.role === "assistant" && m.toolCalls && m.toolCalls.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 3, width: "100%" }}>
                  {m.toolCalls.map((tc, j) => (
                    <div key={j} style={{ display: "inline-flex", alignItems: "center", gap: 6, alignSelf: "flex-start", background: tc.done ? "#f0fdf4" : "#faf5ff", border: `1px solid ${tc.done ? "#bbf7d0" : "#e9d5ff"}`, borderRadius: 8, padding: "4px 10px", fontSize: 11.5, color: tc.done ? "#16a34a" : "#7c3aed" }}>
                      {!tc.done ? <Spin size="small" /> : <span>✓</span>}
                      <span style={{ fontFamily: "monospace", letterSpacing: "-0.2px" }}>{tc.name}({tc.params})</span>
                    </div>
                  ))}
                </div>
              )}
              {(m.role === "user" || m.content || (m.role === "assistant" && (!m.toolCalls || m.toolCalls.every(tc => tc.done)))) && (
                <div style={{ background: m.role === "user" ? "linear-gradient(135deg,#4f46e5,#7c3aed)" : "#fff", color: m.role === "user" ? "#fff" : "#1f2937", borderRadius: m.role === "user" ? "16px 4px 16px 16px" : "4px 16px 16px 16px", padding: "10px 14px", fontSize: 13.5, lineHeight: 1.65, boxShadow: m.role === "user" ? "0 2px 12px rgba(79,70,229,0.25)" : "0 1px 4px rgba(0,0,0,0.07)", border: m.role === "assistant" ? "1px solid #f0f0f8" : "none" }}>
                  {m.role === "assistant"
                    ? m.content ? <div className="chat-md markdown-body" style={{ fontSize: 13.5, background: "transparent", lineHeight: 1.7 }}><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeHighlight, rehypeKatex]}>{normalizeMathDelimiters(m.content)}</ReactMarkdown></div> : "▋"
                    : m.content}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ padding: "12px 14px", flexShrink: 0, background: "#fff", borderTop: "1px solid #eef0f6" }}>
        {attachments.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {attachments.map((att, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 5, background: "#f0f0ff", border: "1px solid #e0e3f8", borderRadius: 8, padding: "3px 8px 3px 6px", fontSize: 12, color: "#4f46e5" }}>
                {att.type === "image" ? <FileImageOutlined style={{ fontSize: 13 }} /> : <FileTextOutlined style={{ fontSize: 13 }} />}
                <span style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{att.name}</span>
                <button onClick={() => setAttachments(prev => prev.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: "#a5b4fc", padding: 0, fontSize: 11 }}>✕</button>
              </div>
            ))}
          </div>
        )}
        <input ref={fileInputRef} type="file" multiple accept="image/*,.pdf,.md,.txt,.csv,.json" style={{ display: "none" }} onChange={handleFileChange} />
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", background: "#f5f6ff", borderRadius: 12, padding: "8px 8px 8px 14px", border: "1px solid #e0e3f8" }}>
          <Tooltip title="上传图片或文件">
            <button onClick={() => fileInputRef.current?.click()} disabled={loading} style={{ border: "none", background: "none", cursor: loading ? "not-allowed" : "pointer", color: "#a5b4fc", padding: 4, borderRadius: 6, display: "flex", alignItems: "center", flexShrink: 0 }}
              onMouseEnter={e => (e.currentTarget.style.color = "#6366f1")} onMouseLeave={e => (e.currentTarget.style.color = "#a5b4fc")}>
              <PaperClipOutlined style={{ fontSize: 16 }} />
            </button>
          </Tooltip>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            onPaste={e => {
              const imageItems = Array.from(e.clipboardData?.items ?? []).filter(item => item.type.startsWith("image/"));
              if (!imageItems.length) return;
              e.preventDefault();
              imageItems.forEach(item => {
                const file = item.getAsFile();
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                  const b64 = (reader.result as string).split(",")[1];
                  setAttachments(prev => [...prev, { name: `粘贴图片_${Date.now()}.png`, type: "image", content: b64, mime: item.type }]);
                };
                reader.readAsDataURL(file);
              });
            }}
            disabled={loading}
            placeholder="针对报告或引用素材提问…"
            rows={2}
            style={{ flex: 1, resize: "none", fontSize: 13.5, border: "none", outline: "none", background: "transparent", lineHeight: 1.6, color: "#1f2937", fontFamily: "inherit" }}
          />
          <button onClick={() => send()} disabled={loading || (!input.trim() && attachments.length === 0)}
            style={{ width: 36, height: 36, borderRadius: 10, border: "none", flexShrink: 0, background: loading || (!input.trim() && attachments.length === 0) ? "#e5e7eb" : "linear-gradient(135deg,#4f46e5,#7c3aed)", color: loading || (!input.trim() && attachments.length === 0) ? "#9ca3af" : "#fff", cursor: loading || (!input.trim() && attachments.length === 0) ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            {loading ? <Spin size="small" indicator={<span style={{ fontSize: 12, color: "#9ca3af" }}>…</span>} /> : <SendOutlined style={{ fontSize: 13 }} />}
          </button>
        </div>
        <div style={{ fontSize: 11, color: "#c4c9d4", marginTop: 6, textAlign: "right" }}>Enter 发送 · Shift+Enter 换行</div>
      </div>
    </div>
  );

  if (inline) return <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>{panelContent}</div>;

  return (
    <>
      {!open && (
        <Tooltip title="针对报告提问" placement="left">
          <button onClick={() => setOpen(true)} style={{ position: "fixed", bottom: 32, right: 32, width: 52, height: 52, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 4px 16px rgba(0,0,0,0.18)", zIndex: 1000, color: "#fff", fontSize: 20 }}>
            <MessageOutlined />
          </button>
        </Tooltip>
      )}
      {open && (
        <div style={{ position: "fixed", bottom: 0, right: 0, width: panelWidth, height: panelHeight, maxHeight: "calc(100vh - 16px)", maxWidth: "calc(100vw - 16px)", background: "#fff", borderTop: "1px solid #e8e8e8", borderLeft: "1px solid #e8e8e8", borderRadius: "12px 0 0 0", boxShadow: "0 -4px 24px rgba(0,0,0,0.10)", display: "flex", flexDirection: "column", zIndex: 999 }}>
          <div onMouseDown={onDragWidthStart} style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 6, cursor: "ew-resize", zIndex: 10, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: 3, height: 36, borderRadius: 2, background: "#d9d9d9" }} />
          </div>
          <div onMouseDown={onDragStart} style={{ height: 6, cursor: "ns-resize", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "#fafafa", borderRadius: "12px 0 0 0" }}>
            <div style={{ width: 36, height: 3, borderRadius: 2, background: "#d9d9d9" }} />
          </div>
          {panelContent}
        </div>
      )}
    </>
  );
});

// ── ReportView ────────────────────────────────────────────────────────────────

export default function ReportView() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(() => localStorage.getItem("reportChatOpen") === "1");
  const [splitPct, setSplitPct] = useState(() => parseFloat(localStorage.getItem("reportSplitPct") ?? "58"));
  const splitDragRef = useRef<{ startX: number; startPct: number } | null>(null);
  const [exporting, setExporting] = useState(false);
  const chatPanelRef = useRef<{ clearHistory: () => void }>(null);

  const toggleChat = (v: boolean) => {
    setChatOpen(v);
    localStorage.setItem("reportChatOpen", v ? "1" : "0");
  };

  const onSplitDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    splitDragRef.current = { startX: e.clientX, startPct: splitPct };
    const onMove = (ev: MouseEvent) => {
      if (!splitDragRef.current) return;
      const delta = ((ev.clientX - splitDragRef.current.startX) / window.innerWidth) * 100;
      setSplitPct(Math.max(25, Math.min(80, splitDragRef.current.startPct + delta)));
    };
    const onUp = (ev: MouseEvent) => {
      if (splitDragRef.current) {
        const delta = ((ev.clientX - splitDragRef.current.startX) / window.innerWidth) * 100;
        localStorage.setItem("reportSplitPct", String(Math.max(25, Math.min(80, splitDragRef.current.startPct + delta))));
      }
      splitDragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTitle, setDrawerTitle] = useState("");
  const [drawerStem, setDrawerStem] = useState("");
  const [drawerContent, setDrawerContent] = useState("");
  const [drawerFileDir, setDrawerFileDir] = useState("");
  const [drawerMeta, setDrawerMeta] = useState<Record<string, unknown> | null>(null);
  const [drawerSourceType, setDrawerSourceType] = useState<SourceType>("note");
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [showPdf, setShowPdf] = useState(false);
  const [drawerWidth, setDrawerWidth] = useState(() => {
    const saved = localStorage.getItem("citationDrawerWidth");
    return saved ? Math.max(480, Math.min(1100, parseInt(saved, 10))) : 700;
  });
  const drawerDragRef = useRef<{ startX: number; startW: number } | null>(null);
  const drawerBodyRef = useRef<HTMLDivElement>(null);

  // Each opened citation reuses the same scroll container, so a new document
  // would otherwise inherit the previous one's scroll offset. Reset to the top
  // once the new content has rendered (drawerLoading false).
  useEffect(() => {
    if (!drawerLoading && !showPdf) drawerBodyRef.current?.scrollTo({ top: 0 });
  }, [drawerStem, drawerLoading, showPdf]);

  const onDrawerResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    drawerDragRef.current = { startX: e.clientX, startW: drawerWidth };
    const onMove = (ev: MouseEvent) => {
      if (!drawerDragRef.current) return;
      const delta = drawerDragRef.current.startX - ev.clientX;
      setDrawerWidth(Math.max(480, Math.min(window.innerWidth * 0.85, drawerDragRef.current.startW + delta)));
    };
    const onUp = (ev: MouseEvent) => {
      if (drawerDragRef.current) {
        const delta = drawerDragRef.current.startX - ev.clientX;
        const w = Math.max(480, Math.min(window.innerWidth * 0.85, drawerDragRef.current.startW + delta));
        localStorage.setItem("citationDrawerWidth", String(Math.round(w)));
      }
      drawerDragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  useEffect(() => {
    apiClient.get<Report>(`/api/reports/${id}`)
      .then(res => setReport(res.data))
      .catch(() => message.error("加载报告失败"))
      .finally(() => setLoading(false));
  }, [id]);

  const openWikilink = useCallback(async (rawName: string) => {
    const name = rawName.replace(/\+$/, "").trim();
    const stem = name.split("/").pop()?.replace(/\.md$/, "") ?? name;
    setDrawerTitle(stem); setDrawerStem(stem); setDrawerContent(""); setDrawerFileDir("");
    setDrawerMeta(null); setDrawerSourceType("note");
    setDrawerOpen(true); setShowPdf(false); setDrawerLoading(true);
    try {
      const res = await apiClient.get<string>(`/api/obsidian/vault/${encodeURIComponent(name)}.md`, { responseType: "text" });
      const raw = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      const fileDir = res.headers?.["x-file-dir"] ?? "";
      const { meta, body } = splitFrontmatter(raw);
      setDrawerContent(body);
      setDrawerMeta(meta);
      setDrawerFileDir(fileDir);
      setDrawerSourceType(detectSourceType(fileDir));
    } catch { setDrawerContent(`*找不到文档：${name}*`); }
    finally { setDrawerLoading(false); }
  }, []);

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const token = localStorage.getItem("token") ?? "";
      const resp = await fetch(`/api/reports/${id}/export`, { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) { message.error("导出失败"); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const disposition = resp.headers.get("content-disposition") ?? "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i);
      a.download = match ? decodeURIComponent(match[1].trim()) : `report_${id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { message.error("导出失败"); }
    finally { setExporting(false); }
  };

  if (loading) return <div style={{ display: "flex", justifyContent: "center", marginTop: 80 }}><Spin size="large" /></div>;
  if (!report) return <div style={{ textAlign: "center", marginTop: 80, color: "#888" }}>报告不存在</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 64px)", overflow: "hidden", background: "#f5f5f5" }}>
      <ReadingProgress scrollContainerId="report-scroll-container" />
      {/* Toolbar */}
      <div style={{ flexShrink: 0, padding: "0 24px", height: 48, display: "flex", alignItems: "center", justifyContent: "space-between", background: "#fff", borderBottom: "1px solid #eef0f6", boxShadow: "0 1px 4px rgba(99,102,241,0.06)" }}>
        <span style={{ fontSize: 13, color: "#9ca3af", fontFamily: "monospace", maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{report.vault_path?.replace(/\\/g, "/").split("/").pop() ?? ""}</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {chatOpen && (
            <Tooltip title="清空对话">
              <button onClick={() => chatPanelRef.current?.clearHistory()}
                style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 10px", borderRadius: 8, border: "1px solid #e0e3f8", cursor: "pointer", fontSize: 13, background: "#f5f6ff", color: "#9ca3af", transition: "all 0.15s" }}
                onMouseEnter={e => { e.currentTarget.style.color = "#ef4444"; e.currentTarget.style.borderColor = "#fca5a5"; e.currentTarget.style.background = "#fff5f5"; }}
                onMouseLeave={e => { e.currentTarget.style.color = "#9ca3af"; e.currentTarget.style.borderColor = "#e0e3f8"; e.currentTarget.style.background = "#f5f6ff"; }}>
                <DeleteOutlined style={{ fontSize: 13 }} />
              </button>
            </Tooltip>
          )}
          <button onClick={() => toggleChat(!chatOpen)}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, background: chatOpen ? "#eef2ff" : "linear-gradient(135deg,#4f46e5,#7c3aed)", color: chatOpen ? "#4f46e5" : "#fff", boxShadow: chatOpen ? "none" : "0 2px 8px rgba(79,70,229,0.25)", transition: "all 0.15s" }}>
            <MessageOutlined style={{ fontSize: 13 }} />
            {chatOpen ? "隐藏问答" : "AI 问答"}
          </button>
          <button onClick={handleExport} disabled={exporting}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: exporting ? "not-allowed" : "pointer", background: "#f5f6ff", color: "#4f46e5", border: "1px solid #e0e3f8", opacity: exporting ? 0.6 : 1, transition: "all 0.15s" }}
            onMouseEnter={e => { if (!exporting) { e.currentTarget.style.background = "#eef2ff"; e.currentTarget.style.borderColor = "#c7d2fe"; } }}
            onMouseLeave={e => { e.currentTarget.style.background = "#f5f6ff"; e.currentTarget.style.borderColor = "#e0e3f8"; }}>
            <DownloadOutlined style={{ fontSize: 13 }} />
            {exporting ? "导出中…" : "导出 ZIP"}
          </button>
        </div>
      </div>

      {/* Main split area */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <div id="report-scroll-container" style={{ width: chatOpen ? `${splitPct}%` : "100%", overflowY: "auto", transition: chatOpen ? "none" : "width 0.2s", paddingBottom: 48 }}>
          <MarkdownContent
            content={report.content}
            onWikiClick={openWikilink}
            fileDir={report.vault_path ? report.vault_path.replace(/\\/g, "/").split("/").slice(0, -1).join("/") : ""}
          />
        </div>
        {chatOpen && (
          <div onMouseDown={onSplitDrag} style={{ width: 6, flexShrink: 0, cursor: "col-resize", background: "#e8e8e8", display: "flex", alignItems: "center", justifyContent: "center", userSelect: "none" }}>
            <div style={{ width: 2, height: 48, borderRadius: 2, background: "#bbb" }} />
          </div>
        )}
        {chatOpen && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#fff", borderLeft: "1px solid #e8e8e8" }}>
            <ReportChatPanel ref={chatPanelRef} reportId={report.id} onClose={() => toggleChat(false)} inline />
          </div>
        )}
      </div>

      <Drawer
        title={
          <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingRight: 8 }}>
            {/* Row 1: source badge + segmented PDF toggle */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                background: SOURCE_TYPE_CONF[drawerSourceType].bg,
                color: SOURCE_TYPE_CONF[drawerSourceType].color,
                border: `1px solid ${SOURCE_TYPE_CONF[drawerSourceType].border}`,
                borderRadius: 6, padding: "2px 9px", fontSize: 11, fontWeight: 700,
                flexShrink: 0, lineHeight: 1.6, letterSpacing: "0.3px",
              }}>
                <span style={{ fontSize: 11, display: "flex", alignItems: "center" }}>{SOURCE_TYPE_ICON[drawerSourceType]}</span>
                {SOURCE_TYPE_CONF[drawerSourceType].label}
              </span>
              <div style={{ flex: 1 }} />
              {/* Pill-style segmented toggle */}
              <div style={{ display: "flex", background: "rgba(99,102,241,0.08)", borderRadius: 8, padding: 3, gap: 2, flexShrink: 0 }}>
                {(["笔记", "PDF"] as const).map((label) => {
                  const active = label === "PDF" ? showPdf : !showPdf;
                  return (
                    <button key={label} onClick={() => setShowPdf(label === "PDF")} style={{
                      padding: "2px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                      background: active ? "#fff" : "transparent",
                      color: active ? "#4f46e5" : "#9ca3af",
                      border: active ? "1px solid #e0e7ff" : "1px solid transparent",
                      cursor: "pointer", transition: "all 0.15s",
                      boxShadow: active ? "0 1px 4px rgba(79,70,229,0.12)" : "none",
                    }}>{label}</button>
                  );
                })}
              </div>
            </div>
            {/* Row 2: title */}
            <div style={{
              fontSize: 14, fontWeight: 700, color: "#1e1b4b", lineHeight: 1.35,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              paddingLeft: 2,
            }}>
              {drawerTitle}
            </div>
          </div>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={drawerWidth}
        styles={{
          header: {
            padding: "14px 52px 12px 20px",
            borderBottom: "1px solid #eef0f8",
            background: "linear-gradient(135deg, #fafbff 0%, #f5f3ff 100%)",
            borderTop: `3px solid ${SOURCE_TYPE_CONF[drawerSourceType].color}`,
          },
          body: { padding: 0, background: "#fff", display: "flex", flexDirection: "column", position: "relative" },
        }}
      >
        {/* ── Left-edge drag-to-resize handle ── */}
        <div
          className="citation-resize-handle"
          onMouseDown={onDrawerResizeStart}
          title="拖拽调整宽度"
        >
          <div className="citation-resize-grip" />
        </div>

        {drawerLoading ? (
          <div style={{ padding: "24px 32px", display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="sk-shimmer" style={{ height: 14, width: "35%", borderRadius: 7 }} />
            <div className="sk-shimmer" style={{ height: 20, width: "90%", borderRadius: 8, marginTop: 4 }} />
            <div className="sk-shimmer" style={{ height: 14, width: "55%", borderRadius: 7 }} />
            <div className="sk-shimmer" style={{ height: 1, width: "100%", borderRadius: 1, margin: "8px 0" }} />
            <div className="sk-shimmer" style={{ height: 72, width: "100%", borderRadius: 10 }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
              {[100, 92, 78, 88, 65].map((w, i) => (
                <div key={i} className="sk-shimmer" style={{ height: 13, width: `${w}%`, borderRadius: 6 }} />
              ))}
            </div>
          </div>
        ) : showPdf ? (
          <iframe
            src={`/api/obsidian/pdf/${encodeURIComponent(drawerStem)}?token=${localStorage.getItem("token") ?? ""}`}
            style={{ flex: 1, width: "100%", height: "calc(100vh - 56px)", border: "none" }}
            title={drawerTitle}
          />
        ) : (
          <div ref={drawerBodyRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
            {drawerMeta && <CitationMetaCard meta={drawerMeta} sourceType={drawerSourceType} />}
            <div className="citation-drawer-body report-md markdown-body" style={{ padding: "20px 28px 32px", fontSize: 14 }}>
              <ReactMarkdown
                remarkPlugins={[remarkFrontmatter, remarkGfm, remarkMath, [remarkWikiLink, wikiLinkOptions]]}
                rehypePlugins={[rehypeHighlight, rehypeKatex, rehypeRaw]}
                components={{
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  ...(({ yaml: _yaml, ...rest }: any) => rest)({ yaml: () => null }),
                  a({ href, children, ...props }) {
                    if (href?.startsWith("/api/obsidian/vault/")) {
                      const name = decodeURIComponent(href.replace("/api/obsidian/vault/", "").replace(/\.md$/, ""));
                      return (
                        <a {...props} href="#" style={{ color: "#722ed1", textDecoration: "underline", textDecorationStyle: "dotted", cursor: "pointer" }}
                          onClick={(e) => { e.preventDefault(); openWikilink(name); }}>
                          {children}
                        </a>
                      );
                    }
                    return <a {...props} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
                  },
                  img({ src, alt, ...props }) {
                    if (!src) return null;
                    if (src.startsWith("http://") || src.startsWith("https://") || src.startsWith("/api/"))
                      return <img src={src} alt={alt} {...props} style={{ maxWidth: "100%", display: "block", margin: "8px 0" }} />;
                    const rel = src.replace(/^\.?\/?/, "");
                    const vaultPath = (drawerFileDir && !rel.includes("/")) ? `${drawerFileDir}/${rel}` : rel;
                    const encodedPath = vaultPath.split("/").map(encodeURIComponent).join("/");
                    return <img src={`/api/obsidian/img/${encodedPath}?token=${localStorage.getItem("token") ?? ""}`} alt={alt} {...props} style={{ maxWidth: "100%", display: "block", margin: "8px 0" }} />;
                  },
                }}
              >
                {renderMathToHtml(escapeSingleTildes(normalizeMathDelimiters(escapeNumericRefLinks(fixObsidianPipe(fixObsidianImages(drawerContent, drawerFileDir, localStorage.getItem("token") ?? ""))))))}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
