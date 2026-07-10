import { useEffect, useRef, useState, useCallback } from "react";
import { Spin, Popconfirm, Tooltip } from "antd";
import {
  SendOutlined,
  PlusOutlined,
  DeleteOutlined,
  RobotOutlined,
  UserOutlined,
  CheckCircleFilled,
  LoadingOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  ExclamationCircleFilled,
  CaretRightOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import { useAskWS, SubQuestion, WsMsg, ReportType } from "@/hooks/useAskWS";



type Tier = "quick" | "normal" | "deep";
type Stage = "idle" | "asking" | "clarifying" | "confirming" | "running" | "done" | "error";

interface Bubble { role: "user" | "bot"; content: string }
interface ProgressItem { step: string; message: string; done: boolean }

interface QuestionSummary {
  id: number; raw_text: string; tier: string; status: string;
  created_at: string; report_id: number | null;
}
interface QuestionDetail extends QuestionSummary {
  clarified_text: string | null; sub_questions: SubQuestion[];
  keywords_draft: string[];
  report_type: ReportType | null; research_params: Record<string, unknown>;
  task: { id: number; status: string; current_step: string | null; keywords: string[] } | null;
}

const STEP_LABELS: Record<string, string> = {
  step3_local_search: "检索公司知识库",
  step3b_me_fetch: "读取 Market Engine",
  step4_coverage: "评估章节覆盖度",
  step5_web_search: "针对缺口补充 Web 来源",
  step6_qc: "组装证据",
  step6b_prewrite_check: "检查写作数据基础",
  step9_report: "生成调研报告",
  step9b_evaluate: "评估报告质量",
  step8_validate: "校验格式与引用",
  step10_reply: "推送报告",
};
const STEP_ORDER = [
  "step3_local_search","step3b_me_fetch","step4_coverage","step5_web_search",
  "step6_qc","step6b_prewrite_check","step9_report","step9b_evaluate","step8_validate","step10_reply",
];
// Question statuses where Step 1 (clarify + keyword extraction) is still running
// on the backend — the panel should show a thinking indicator and poll for the
// transition rather than rendering an idle/empty state.
const STEP1_PENDING = ["created", "step1_clarify", "step1_keywords"];

function buildHistoryProgress(currentStep: string | null | undefined): ProgressItem[] {
  if (!currentStep) return [];
  const idx = STEP_ORDER.indexOf(currentStep);
  if (idx === -1) return [{ step: currentStep, message: STEP_LABELS[currentStep] ?? currentStep, done: false }];
  return STEP_ORDER.slice(0, idx + 1).map((step, i) => ({
    step, message: STEP_LABELS[step] ?? step, done: i < idx,
  }));
}

// ─── AI avatar (premium, animated) ─────────────────────────────────────────────
function SparkleGlyph({ size, className }: { size: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      {/* large 4-point sparkle */}
      <path
        d="M12 2.4c.45 3.85 2.05 5.45 5.9 5.9-3.85.45-5.45 2.05-5.9 5.9-.45-3.85-2.05-5.45-5.9-5.9 3.85-.45 5.45-2.05 5.9-5.9Z"
        fill="currentColor"
      />
      {/* small accent sparkle */}
      <path
        d="M18.4 13.2c.2 1.95.95 2.7 2.9 2.95-1.95.2-2.7.95-2.95 2.9-.2-1.95-.95-2.7-2.9-2.95 1.95-.25 2.7-.95 2.95-2.9Z"
        fill="currentColor"
        opacity="0.9"
      />
    </svg>
  );
}

function AiAvatar({ size = 32, rounded = "rounded-full" }: { size?: number; rounded?: string }) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-hidden="true">
      {/* ambient breathing glow */}
      <div className={`absolute -inset-1 ${rounded} ai-avatar-glow blur-md`} />
      {/* gradient core */}
      <div className={`relative w-full h-full ${rounded} ai-avatar-grad flex items-center justify-center overflow-hidden shadow-lg shadow-violet-300/50`}>
        {/* light sheen sweep */}
        <span className="absolute inset-y-0 left-0 w-1/3 bg-white/30 blur-[2px] ai-avatar-sheen" />
        {/* twinkling sparkle */}
        <SparkleGlyph size={Math.round(size * 0.58)} className="ai-avatar-spark relative text-white drop-shadow-sm" />
      </div>
    </div>
  );
}

// ─── Typing dots ──────────────────────────────────────────────────────────────
function TypingDots() {
  return (
    <div className="flex items-end gap-2 mb-4">
      <AiAvatar size={32} />
      <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm flex gap-1 items-center">
        {[0,1,2].map(i => (
          <span key={i} className="w-1.5 h-1.5 rounded-full bg-gray-300 inline-block"
            style={{ animation: `bounce 1.2s ${i*0.2}s ease-in-out infinite` }} />
        ))}
      </div>
      <style>{`@keyframes bounce{0%,60%,100%{transform:translateY(0);background:#d1d5db}30%{transform:translateY(-6px);background:#6366f1}}`}</style>
    </div>
  );
}

// ─── Chat bubble ──────────────────────────────────────────────────────────────
function ChatBubble({ role, content }: Bubble) {
  const isUser = role === "user";
  return (
    <div className={`flex items-end gap-2.5 mb-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {isUser ? (
        <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-md bg-gradient-to-br from-emerald-400 to-teal-500 shadow-emerald-100">
          <UserOutlined className="text-white text-sm" />
        </div>
      ) : (
        <AiAvatar size={32} />
      )}
      <div className={`max-w-[68%] px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words shadow-sm ${
        isUser
          ? "bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-2xl rounded-br-sm shadow-blue-100"
          : "bg-white text-gray-800 border border-gray-100 rounded-2xl rounded-bl-sm"
      }`}>
        {content}
      </div>
    </div>
  );
}

// ─── Keyword confirm card ─────────────────────────────────────────────────────
function KeywordConfirmCard({ questionId, subQuestions, initialKeywords, initialTier, initialReportType, researchParams, onConfirm, onCancel }: {
  questionId: number; subQuestions: SubQuestion[];
  initialKeywords: string[]; initialTier: Tier; initialReportType: ReportType; researchParams: Record<string, unknown>;
  onConfirm: (qid: number, kws: string[], tier: Tier, sqs: SubQuestion[], reportType: ReportType, params: Record<string, unknown>) => void;
  onCancel: (qid: number) => void;
}) {
  const [keywords, setKeywords] = useState(initialKeywords);
  const [inputVal, setInputVal] = useState("");
  const [tier, setTier] = useState<Tier>(initialTier);
  const [reportType, setReportType] = useState<ReportType>(initialReportType);
  const [editingKw, setEditingKw] = useState(false);
  const [sqs, setSqs] = useState<SubQuestion[]>(subQuestions);
  const [editingSq, setEditingSq] = useState(false);
  const [newSqText, setNewSqText] = useState("");

  const addKeyword = () => {
    const v = inputVal.trim();
    if (v && !keywords.includes(v)) setKeywords(p => [...p, v]);
    setInputVal("");
  };

  const updateSq = (idx: number, text: string) =>
    setSqs(prev => prev.map((sq, i) => i === idx ? { ...sq, text } : sq));

  const deleteSq = (idx: number) =>
    setSqs(prev => prev.filter((_, i) => i !== idx));

  const addSq = () => {
    const text = newSqText.trim();
    if (!text) return;
    setSqs(prev => [...prev, { id: `Q${prev.length + 1}`, text }]);
    setNewSqText("");
  };

  const TIERS: { key: Tier; icon: string; label: string; desc: string }[] = [
    { key: "quick",  icon: "⚡", label: "快速", desc: "仅本地，不搜 Web" },
    { key: "normal", icon: "📋", label: "标准", desc: "KB + ME + Web" },
    { key: "deep",   icon: "🔬", label: "深度", desc: "扩大 Web 证据" },
  ];
  const REPORTS: { key: ReportType; icon: string; label: string }[] = [
    { key: "market", icon: "📊", label: "市场研究" },
    { key: "product", icon: "📦", label: "产品研究" },
    { key: "competitive", icon: "⚔️", label: "竞品分析" },
    { key: "technology", icon: "🔬", label: "技术研究" },
  ];

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-lg shadow-gray-100/60 p-5 max-w-lg">
      {/* title */}
      <div className="flex items-center gap-2.5 mb-4">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-sm">
          🔍
        </div>
        <span className="font-semibold text-gray-800 text-[15px]">确认研究方向</span>
      </div>

      {/* sub questions */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">分解子问题</p>
          <button onClick={() => setEditingSq(v => !v)}
            className="text-xs text-blue-500 hover:text-blue-700 transition-colors">
            {editingSq ? "完成" : "✏️ 编辑"}
          </button>
        </div>
        <div className="flex flex-col gap-1.5">
          {sqs.map((sq, i) => (
            <div key={sq.id} className="flex gap-2 items-start bg-slate-50 rounded-xl px-3 py-2">
              <span className="w-5 h-5 rounded-md bg-blue-100 text-blue-600 text-[11px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                {i + 1}
              </span>
              {editingSq ? (
                <div className="flex flex-1 gap-1.5 items-center min-w-0">
                  <input
                    value={sq.text}
                    onChange={e => updateSq(i, e.target.value)}
                    className="flex-1 text-sm text-gray-700 bg-white border border-gray-200 rounded-lg px-2 py-1 outline-none focus:border-blue-400 min-w-0"
                  />
                  <button onClick={() => deleteSq(i)}
                    className="text-gray-300 hover:text-red-500 text-sm shrink-0 leading-none">×</button>
                </div>
              ) : (
                <span className="text-sm text-gray-700 leading-relaxed">{sq.text}</span>
              )}
            </div>
          ))}
          {editingSq && (
            <div className="flex gap-1.5 items-center mt-1">
              <input
                value={newSqText}
                onChange={e => setNewSqText(e.target.value)}
                onKeyDown={e => e.key === "Enter" && addSq()}
                placeholder="添加子问题..."
                className="flex-1 text-sm border border-dashed border-gray-300 rounded-xl px-3 py-1.5 outline-none focus:border-blue-400 bg-transparent"
              />
              <button onClick={addSq}
                className="text-xs text-blue-500 hover:text-blue-700 bg-blue-50 px-2.5 py-1.5 rounded-lg shrink-0">
                添加
              </button>
            </div>
          )}
        </div>
      </div>

      {/* keywords */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">搜索关键词</p>
          <button onClick={() => {
              if (editingKw) { addKeyword(); } // commit pending input before closing
              setEditingKw(v => !v);
            }}
            className="text-xs text-blue-500 hover:text-blue-700 transition-colors">
            {editingKw ? "完成" : "✏️ 编辑"}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {keywords.map(kw => (
            <span key={kw} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[13px] font-medium ${
              editingKw
                ? "bg-gray-100 text-gray-700"
                : "bg-blue-50 text-blue-700 border border-blue-200"
            }`}>
              {kw}
              {editingKw && (
                <button onClick={() => setKeywords(p => p.filter(k => k !== kw))}
                  className="text-gray-400 hover:text-red-500 ml-0.5 leading-none">×</button>
              )}
            </span>
          ))}
          {editingKw && (
            <div className="inline-flex items-center gap-1">
              <input
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                onKeyDown={e => e.key === "Enter" && addKeyword()}
                placeholder="添加..."
                className="w-24 px-2 py-1 text-sm border border-dashed border-gray-300 rounded-lg outline-none focus:border-blue-400 bg-transparent"
              />
              <button onClick={addKeyword}
                className="text-xs text-blue-500 hover:text-blue-700 bg-blue-50 px-2 py-1 rounded-lg shrink-0">
                添加
              </button>
            </div>
          )}
        </div>
      </div>

      {/* report type */}
      <div className="mb-4">
        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">报告类型</p>
        <div className="grid grid-cols-2 gap-2">
          {REPORTS.map(r => (
            <button key={r.key} onClick={() => setReportType(r.key)}
              className={`px-3 py-2 rounded-xl border-2 text-left text-sm transition-all ${
                reportType === r.key
                  ? "border-violet-500 bg-violet-50 text-violet-700"
                  : "border-gray-200 bg-gray-50 text-gray-600 hover:border-gray-300"
              }`}>
              {r.icon} <span className="font-semibold">{r.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* tier */}
      <div className="mb-5">
        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">搜索档位</p>
        <div className="grid grid-cols-3 gap-2">
          {TIERS.map(t => (
            <button key={t.key} onClick={() => setTier(t.key)}
              className={`flex flex-col items-start gap-0.5 px-3 py-2.5 rounded-xl border-2 text-left transition-all ${
                tier === t.key
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-200 bg-gray-50 hover:border-gray-300"
              }`}>
              <span className="text-[13px]">{t.icon} <span className={`font-semibold ${tier === t.key ? "text-blue-600" : "text-gray-700"}`}>{t.label}</span></span>
              <span className="text-[11px] text-gray-400">{t.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onConfirm(questionId, keywords, tier, sqs, reportType, researchParams)}
          className="flex-1 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white font-semibold py-2.5 rounded-xl flex items-center justify-center gap-2 text-sm transition-all shadow-md shadow-blue-200 active:scale-[0.98]">
          <CheckCircleFilled />
          确认，开始研究
        </button>
        <button
          onClick={() => onCancel(questionId)}
          className="w-16 border-2 border-red-200 text-red-400 hover:border-red-400 hover:text-red-500 font-medium py-2.5 rounded-xl text-sm transition-all">
          取消
        </button>
      </div>
    </div>
  );
}

// ─── Pipeline progress (with per-step expandable detail) ─────────────────────

interface StepDetail {
  step: string;
  label: string;
  done: boolean;
  summary: string;
  detail: Record<string, unknown>;
}

function StepDetailPanel({ step, detail }: { step: string; detail: Record<string, unknown> }) {
  const coverageColor = (v: string) =>
    v === "✅" ? "text-emerald-600 bg-emerald-50" : v === "⚠️" ? "text-amber-600 bg-amber-50" : "text-red-500 bg-red-50";

  if (step === "step3_local_search") {
    const cov = (detail.initial_coverage as Record<string, string>) ?? {};
    const titles = (detail.titles as string[]) ?? [];
    return (
      <div className="space-y-2">
        {Object.keys(cov).length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">子问题覆盖</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(cov).map(([q, v]) => (
                <span key={q} className={`text-[11px] px-2 py-0.5 rounded-md font-medium ${coverageColor(v)}`}>{q}: {v}</span>
              ))}
            </div>
          </div>
        )}
        {titles.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">命中文献</p>
            <div className="space-y-1">
              {titles.map((t, i) => (
                <div key={i} className="text-[12px] text-gray-600 bg-gray-50 rounded-lg px-3 py-1.5 truncate">{t || "—"}</div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (step === "step4_backtrack") {
    const panorama = (detail.panorama as Array<Record<string, string>>) ?? [];
    return (
      <div>
        <p className="text-[11px] text-gray-400 font-semibold mb-1.5">技术全景表</p>
        <div className="space-y-1">
          {panorama.map((r, i) => (
            <div key={i} className="flex items-center gap-2 text-[12px] bg-gray-50 rounded-lg px-3 py-1.5">
              <span className={`text-[11px] px-1.5 py-0.5 rounded font-bold ${coverageColor(r.coverage ?? "")}`}>{r.coverage}</span>
              <span className="text-gray-400 text-[10px] bg-gray-200 px-1.5 rounded">{r.category}</span>
              <span className="text-gray-700 truncate">{r.direction}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (step === "step5_decide") {
    const sqs = (detail.sub_questions as Array<Record<string, string>>) ?? [];
    const gaps = (detail.gaps as Array<Record<string, string>>) ?? [];
    return (
      <div className="space-y-2">
        {sqs.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">子问题覆盖</p>
            <div className="space-y-1">
              {sqs.map(sq => (
                <div key={sq.id} className="flex items-start gap-2 text-[12px] bg-gray-50 rounded-lg px-3 py-1.5">
                  <span className={`text-[11px] px-1.5 py-0.5 rounded font-bold shrink-0 ${coverageColor(sq.coverage ?? "")}`}>{sq.id}</span>
                  <span className="text-gray-700">{sq.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {gaps.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">待补搜缺口</p>
            <div className="flex flex-wrap gap-1.5">
              {gaps.map((g, i) => (
                <span key={i} className="text-[11px] bg-orange-50 text-orange-600 border border-orange-200 px-2 py-0.5 rounded-md">{g.direction ?? JSON.stringify(g)}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (step === "step6_ieee" || step === "step7_patent") {
    const downloaded = (detail.downloaded as string[]) ?? [];
    return (
      <div>
        <p className="text-[11px] text-gray-400 font-semibold mb-1.5">已下载</p>
        <div className="space-y-1">
          {downloaded.length === 0
            ? <p className="text-[12px] text-gray-400">暂无</p>
            : downloaded.map((t, i) => (
                <div key={i} className="text-[12px] text-gray-600 bg-gray-50 rounded-lg px-3 py-1.5 truncate">{t || "—"}</div>
              ))
          }
        </div>
      </div>
    );
  }

  if (step === "step7b_web") {
    const urls = (detail.urls as string[]) ?? [];
    return (
      <div>
        <p className="text-[11px] text-gray-400 font-semibold mb-1.5">归档页面</p>
        <div className="space-y-1">
          {urls.map((u, i) => <div key={i} className="text-[12px] text-blue-600 bg-blue-50 rounded-lg px-3 py-1.5 truncate">{u}</div>)}
        </div>
      </div>
    );
  }

  if (step === "step8_gate") {
    const scores = (detail.top_scores as Array<Record<string, unknown>>) ?? [];
    const gate = (detail.gate_results as Record<string, unknown>) ?? {};
    return (
      <div className="space-y-2">
        {scores.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">阅读评分 Top</p>
            <div className="space-y-1">
              {scores.map((s, i) => (
                <div key={i} className="flex items-center gap-2 text-[12px] bg-gray-50 rounded-lg px-3 py-1.5">
                  <span className={`w-6 h-6 rounded-md text-[11px] font-bold flex items-center justify-center shrink-0 ${
                    Number(s.score) >= 4 ? "bg-emerald-100 text-emerald-700" : Number(s.score) >= 3 ? "bg-blue-100 text-blue-700" : "bg-gray-200 text-gray-500"
                  }`}>{String(s.score)}</span>
                  <span className="text-gray-700 truncate">{String(s.paper ?? "")}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {Object.keys(gate).length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 font-semibold mb-1.5">Gate 结果</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(gate).map(([k, v]) => (
                <span key={k} className={`text-[11px] px-2 py-0.5 rounded-md font-medium ${v === 0 || v === "pass" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"}`}>
                  {k}: {String(v)}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (step === "step9_report") {
    return (
      <div>
        <p className="text-[11px] text-gray-400 font-semibold mb-1.5">报告路径</p>
        <p className="text-[12px] text-gray-600 bg-gray-50 rounded-lg px-3 py-1.5 break-all">{String(detail.report_path ?? "—")}</p>
      </div>
    );
  }

  return null;
}

function PipelineProgress({ items, allDone, taskId }: { items: ProgressItem[]; allDone: boolean; taskId: number | null }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [stepDetails, setStepDetails] = useState<Record<string, StepDetail>>({});

  // Fetch context whenever taskId is available or allDone changes
  useEffect(() => {
    if (!taskId) return;
    const fetch = () => {
      apiClient.get<{ steps: StepDetail[] }>(`/api/tasks/${taskId}/context`).then(res => {
        const map: Record<string, StepDetail> = {};
        for (const s of res.data.steps) map[s.step] = s;
        setStepDetails(map);
      }).catch(() => {/* ignore */});
    };
    fetch();
    if (!allDone) {
      const id = setInterval(fetch, 4000);
      return () => clearInterval(id);
    }
  }, [taskId, allDone]);

  if (items.length === 0) return null;

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-md shadow-gray-100/60 overflow-hidden max-w-md">
      {/* header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-50">
        <span className={`w-2 h-2 rounded-full shrink-0 ${allDone ? "bg-emerald-400" : "bg-blue-400"}`} />
        <span className="text-[11px] font-bold tracking-widest text-gray-400 uppercase">
          {allDone ? "流水线完成" : "运行中"}
        </span>
      </div>

      {/* steps */}
      <div className="divide-y divide-gray-50">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          const active = isLast && !item.done && !allDone;
          const done = item.done || allDone;
          const detail = stepDetails[item.step];
          const isExpanded = expanded === item.step;
          const hasDetail = !!detail;

          return (
            <div key={item.step}>
              <button
                onClick={() => hasDetail && setExpanded(isExpanded ? null : item.step)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${hasDetail ? "hover:bg-gray-50 cursor-pointer" : "cursor-default"}`}
              >
                {/* icon */}
                <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                  done ? "bg-emerald-100" : active ? "bg-blue-100" : "bg-gray-100"
                }`}>
                  {done
                    ? <CheckCircleFilled className="text-emerald-500 text-[11px]" />
                    : active
                      ? <LoadingOutlined className="text-blue-500 text-[11px]" spin />
                      : <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                  }
                </div>

                {/* label + summary */}
                <div className="flex-1 min-w-0">
                  <span className={`text-[13px] block ${done ? "text-gray-400" : active ? "text-gray-800 font-medium" : "text-gray-300"}`}>
                    {item.message}
                  </span>
                  {detail?.summary && (
                    <span className="text-[11px] text-gray-400 block truncate">{detail.summary}</span>
                  )}
                </div>

                {/* expand chevron */}
                {hasDetail && (
                  <span className={`text-gray-300 text-xs transition-transform ${isExpanded ? "rotate-180" : ""}`}>▾</span>
                )}
              </button>

              {/* expanded detail */}
              {isExpanded && detail && (
                <div className="px-4 pb-3 pt-1 bg-gray-50/60 border-t border-gray-100">
                  <StepDetailPanel step={item.step} detail={detail.detail} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Sidebar item ─────────────────────────────────────────────────────────────
function SidebarItem({ q, isSelected, onSelect, onDelete }: {
  q: QuestionSummary; isSelected: boolean;
  onSelect: () => void; onDelete: () => void;
}) {
  const isActive = !["done","failed","cancelled"].includes(q.status);
  const date = new Date(q.created_at);
  const dateStr = `${date.getMonth()+1}/${date.getDate()} ${String(date.getHours()).padStart(2,"0")}:${String(date.getMinutes()).padStart(2,"0")}`;

  return (
    <div onClick={onSelect}
      className={`group relative px-4 py-3 cursor-pointer border-b border-gray-100 transition-all ${
        isSelected
          ? "bg-blue-50 border-l-2 border-l-blue-500"
          : "border-l-2 border-l-transparent hover:bg-gray-50"
      }`}>
      {/* status + delete */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${
            q.status === "done" ? "bg-emerald-400"
            : q.status === "failed" ? "bg-red-400"
            : q.status === "cancelled" ? "bg-gray-300"
            : "bg-blue-400"
          }`} />
          <span className={`text-[11px] font-medium ${
            q.status === "done" ? "text-emerald-600"
            : q.status === "failed" ? "text-red-500"
            : q.status === "cancelled" ? "text-gray-400"
            : "text-blue-500"
          }`}>
            {q.status === "done" ? "完成" : q.status === "failed" ? "失败" : q.status === "cancelled" ? "已取消" : "进行中"}
          </span>
        </div>
        <Popconfirm
          title={isActive ? "取消并删除？" : "删除对话？"}
          description={isActive ? "将取消正在进行的任务。" : "仅移除记录，不影响已生成的报告。"}
          okText="确认" cancelText="取消" okButtonProps={{ danger: true, size: "small" }}
          onConfirm={e => { e?.stopPropagation(); onDelete(); }}
          onPopupClick={e => e.stopPropagation()}
        >
          <button
            onClick={e => e.stopPropagation()}
            className="ask-history-delete opacity-0 group-hover:opacity-100 w-6 h-6 flex items-center justify-center rounded-lg text-gray-300 hover:text-red-400 hover:bg-red-50 transition-all text-xs">
            <DeleteOutlined />
          </button>
        </Popconfirm>
      </div>

      {/* question text */}
      <p className={`text-[13px] leading-snug line-clamp-2 mb-1.5 ${isSelected ? "text-blue-700 font-medium" : "text-gray-700"}`}>
        {q.raw_text}
      </p>

      {/* meta */}
      <div className="flex items-center gap-2">
        <ClockCircleOutlined className="text-gray-300 text-[10px]" />
        <span className="text-[11px] text-gray-400">{dateStr}</span>
        {q.report_id && (
          <span className="text-[11px] text-emerald-600 bg-emerald-50 border border-emerald-200 px-1.5 rounded-md font-medium">报告</span>
        )}
      </div>
    </div>
  );
}

// ─── Chat panel ───────────────────────────────────────────────────────────────
interface ChatPanelProps {
  questionId: number | null;
  onQuestionCreated: (id: number) => void;
  connected: boolean;
  send: (msg: Parameters<ReturnType<typeof useAskWS>["send"]>[0]) => void;
  lastMessage: ReturnType<typeof useAskWS>["lastMessage"];
  wsHistory: WsMsg[];
}

function ChatPanel({ questionId, onQuestionCreated, connected, send, lastMessage, wsHistory }: ChatPanelProps) {
  const navigate = useNavigate();
  const [stage, setStage] = useState<Stage>("idle");
  const [inputText, setInputText] = useState("");
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [currentTier, setCurrentTier] = useState<Tier>("normal");
  const [currentQuestionId, setCurrentQuestionId] = useState<number | null>(null);
  const [kwCard, setKwCard] = useState<{ questionId: number; subQuestions: SubQuestion[]; keywords: string[]; tier: Tier; reportType: ReportType; researchParams: Record<string, unknown> } | null>(null);
  const [progressItems, setProgressItems] = useState<ProgressItem[]>([]);
  const [currentTaskId, setCurrentTaskId] = useState<number | null>(null);
  const [reportId, setReportId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Polls the Question record while it is still in a Step 1 (clarify/keyword) state,
  // so a session re-opened mid-thinking catches the transition to card / clarify / running.
  const qPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const processedRef = useRef<Set<WsMsg>>(new Set());
  // True only while this panel is awaiting the response to an "ask" it just sent.
  // Gates whether a blank (questionId=null) panel may adopt an incoming message.
  const askingRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
  }, []);

  const stopQPolling = useCallback(() => {
    if (qPollingRef.current) { clearInterval(qPollingRef.current); qPollingRef.current = null; }
  }, []);

  useEffect(() => () => { stopPolling(); stopQPolling(); }, [stopPolling, stopQPolling]);

  const startPolling = useCallback((taskId: number, qid: number) => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await apiClient.get<{ status: string; current_step: string | null }>(`/api/tasks/${taskId}`);
        const { status, current_step } = res.data;
        if (["done","failed","cancelled"].includes(status)) {
          stopPolling();
          if (status === "done") {
            const qRes = await apiClient.get<QuestionDetail>(`/api/questions/${qid}`);
            setStage("done"); setReportId(qRes.data.report_id);
            setProgressItems(STEP_ORDER.map(s => ({ step: s, message: STEP_LABELS[s] ?? s, done: true })));
            setBubbles(prev => prev.some(b => b.content.startsWith("✅")) ? prev : [...prev, { role: "bot", content: "✅ 调研报告已生成！" }]);
          } else {
            setStage("error");
            setErrorMsg(status === "cancelled" ? "任务已取消" : "流水线执行失败");
          }
        } else if (current_step) {
          setProgressItems(buildHistoryProgress(current_step));
        }
      } catch { /* ignore */ }
    }, 3000);
  }, [stopPolling]);

  // Apply a freshly-fetched question detail to panel state. Idempotent: rebuilds
  // bubbles from scratch, so it is safe to call repeatedly from a poll.
  const applyDetail = useCallback((q: QuestionDetail) => {
    setCurrentQuestionId(q.id); setCurrentTier(q.tier as Tier);
    // The DB record is authoritative: clear any keyword card that a stale WS-history
    // replay may have shown. Only the awaiting_keyword branch below re-adds it, so a
    // question that has already moved on (running/done/…) never keeps the card.
    setKwCard(null);
    const nb: Bubble[] = [{ role: "user", content: q.raw_text }];
    if (q.clarified_text && q.clarified_text !== q.raw_text)
      nb.push({ role: "user", content: `补充信息：${q.clarified_text}` });

    if (q.status === "done") {
      stopQPolling();
      setStage("done"); if (q.report_id) setReportId(q.report_id);
      if (q.task?.keywords?.length) nb.push({ role: "user", content: `已确认关键词：${q.task.keywords.join(", ")}` });
      setProgressItems(STEP_ORDER.map(s => ({ step: s, message: STEP_LABELS[s] ?? s, done: true })));
      nb.push({ role: "bot", content: q.report_id ? "✅ 调研报告已生成！" : "✅ 流水线已完成。" });
      setBubbles(nb);
    } else if (q.status === "failed") {
      stopQPolling();
      setStage("error"); setErrorMsg("流水线执行失败"); setBubbles(nb);
    } else if (q.status === "cancelled") {
      stopQPolling();
      setStage("error"); setErrorMsg("任务已取消"); setBubbles(nb);
    } else if (q.status === "awaiting_keyword" && q.keywords_draft.length > 0) {
      stopQPolling();
      setStage("confirming");
      setKwCard({ questionId: q.id, subQuestions: q.sub_questions, keywords: q.keywords_draft, tier: q.tier as Tier, reportType: q.report_type || "market", researchParams: q.research_params || {} });
      setBubbles(nb);
    } else if (q.status === "awaiting_clarify") {
      stopQPolling();
      setStage("clarifying");
      nb.push({ role: "bot", content: '请补充更多信息，或回复"跳过"继续。' });
      setBubbles(nb);
    } else if (q.task && !["cancelled","failed"].includes(q.task.status)) {
      stopQPolling();
      setStage("running");
      setCurrentTaskId(q.task.id);
      if (q.task.keywords?.length) nb.push({ role: "user", content: `已确认关键词：${q.task.keywords.join(", ")}` });
      setProgressItems(buildHistoryProgress(q.task.current_step));
      setBubbles(nb); startPolling(q.task.id, q.id);
    } else if (STEP1_PENDING.includes(q.status)) {
      // AI is still clarifying / extracting keywords (Step 1). Show the thinking
      // indicator and keep polling so the keyword card / clarify prompt appears
      // even if the live WS push was missed while this panel was unmounted.
      setStage("asking"); setBubbles(nb);
    } else {
      setStage("idle"); setBubbles(nb);
    }
  }, [startPolling, stopQPolling]);

  useEffect(() => {
    stopPolling();
    stopQPolling();
    if (!questionId) {
      askingRef.current = false;
      setStage("idle"); setBubbles([]); setProgressItems([]);
      setKwCard(null); setReportId(null); setErrorMsg(null); setCurrentQuestionId(null); setCurrentTaskId(null);
      return;
    }
    setLoadingHistory(true);
    apiClient.get<QuestionDetail>(`/api/questions/${questionId}`).then(res => {
      applyDetail(res.data);
      // If still in a Step 1 thinking state, poll until it transitions.
      if (STEP1_PENDING.includes(res.data.status)) {
        qPollingRef.current = setInterval(() => {
          apiClient.get<QuestionDetail>(`/api/questions/${questionId}`)
            .then(r => applyDetail(r.data))
            .catch(() => {/* ignore */});
        }, 3000);
      }
    }).catch(() => setStage("idle")).finally(() => setLoadingHistory(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [bubbles, progressItems]);

  const applyWsMsg = useCallback((msg: WsMsg) => {
    if (processedRef.current.has(msg)) return;

    const msgQid = (msg as { question_id?: number }).question_id;
    if (questionId !== null) {
      // This panel owns a question: ignore traffic for any other question.
      if (msgQid !== undefined && msgQid !== questionId) return;
    } else {
      // Blank/new panel: only adopt a question from the direct response to an
      // "ask" we just sent from THIS panel. Other running tasks share the same
      // WS connection — without this guard their progress/done/error would leak
      // into the empty panel.
      if (!askingRef.current) return;
      if (msg.type !== "clarify" && msg.type !== "keywords" && msg.type !== "mra_params" && msg.type !== "invalid") return;
      askingRef.current = false; // ask has now been answered
    }

    processedRef.current.add(msg);
    // A live WS message means Step 1 has produced output (or the pipeline moved on),
    // so any in-progress Step 1 poll is no longer needed.
    stopQPolling();

    if (msg.type === "clarify") {
      setStage("clarifying"); setCurrentQuestionId(msg.question_id);
      setBubbles(prev => [...prev, { role: "bot", content: msg.message }]);
      if (!questionId) onQuestionCreated(msg.question_id);
    } else if (msg.type === "invalid") {
      setStage("idle");
      setBubbles(prev => [...prev, { role: "bot", content: msg.message }]);
    } else if (msg.type === "keywords" || msg.type === "mra_params") {
      setStage("confirming"); setCurrentQuestionId(msg.question_id);
      setKwCard({ questionId: msg.question_id, subQuestions: msg.sub_questions, keywords: msg.keywords, tier: (msg.tier as Tier) || "normal", reportType: msg.type === "mra_params" ? msg.report_type : "market", researchParams: msg.type === "mra_params" ? msg.research_params : {} });
      if (!questionId) onQuestionCreated(msg.question_id);
    } else if (msg.type === "progress") {
      stopPolling();
      setCurrentTaskId(msg.task_id);
      setProgressItems(prev => [...prev.map(p => ({ ...p, done: true })), { step: msg.step, message: msg.message, done: false }]);
    } else if (msg.type === "done") {
      stopPolling(); setStage("done"); setReportId(msg.report_id);
      setCurrentTaskId(msg.task_id);
      setProgressItems(prev => prev.map(p => ({ ...p, done: true })));
      setBubbles(prev => prev.some(b => b.content.startsWith("✅")) ? prev : [...prev, {
        role: "bot", content: msg.report_id ? "✅ 调研报告已生成！" : "✅ 流水线完成（未生成报告）。"
      }]);
    } else if (msg.type === "error") {
      stopPolling(); setStage("error"); setErrorMsg((msg as { message: string }).message);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId, stopPolling, stopQPolling]);

  const wsHistoryApplied = useRef(false);
  useEffect(() => {
    if (wsHistoryApplied.current || wsHistory.length === 0) return;
    wsHistoryApplied.current = true; wsHistory.forEach(applyWsMsg);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { if (lastMessage) applyWsMsg(lastMessage); }, [lastMessage, applyWsMsg]);
  useEffect(() => { if (kwCard && !currentQuestionId) setCurrentQuestionId(kwCard.questionId); }, [kwCard, currentQuestionId]);

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || ["running","confirming","done"].includes(stage)) return;
    if (stage === "idle") {
      setBubbles([{ role: "user", content: text }]); setInputText("");
      setStage("asking"); setProgressItems([]); setKwCard(null);
      setReportId(null); setErrorMsg(null); setCurrentQuestionId(null);
      askingRef.current = true; // expect the response to adopt this panel's question
      send({ type: "ask", text, tier: currentTier });
    } else if (stage === "clarifying" && currentQuestionId !== null) {
      setBubbles(prev => [...prev, { role: "user", content: text }]);
      setInputText(""); send({ type: "clarify_reply", question_id: currentQuestionId, text });
    }
  };

  const handleConfirm = (qid: number, keywords: string[], tier: Tier, sqs: SubQuestion[], reportType: ReportType, researchParams: Record<string, unknown>) => {
    setKwCard(null); setStage("running");
    setBubbles(prev => [...prev, { role: "user", content: `已确认关键词：${keywords.join(", ")}（${tier === "quick" ? "快速" : tier === "deep" ? "深度" : "标准"}）` }]);
    send({ type: "confirm_keywords", question_id: qid, keywords, tier, sub_questions: sqs, report_type: reportType, research_params: researchParams });
  };

  const handleCancel = (qid: number) => {
    setKwCard(null); setStage("idle"); setBubbles([]); setProgressItems([]);
    send({ type: "cancel", question_id: qid }); navigate("/ask");
  };

  const isDisabled = !connected || ["asking","running","confirming","done"].includes(stage);

  if (loadingHistory) {
    return <div className="flex-1 flex items-center justify-center"><Spin /></div>;
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-gray-50/60">
      {/* header */}
      <div className="flex items-center gap-3 px-6 py-3.5 bg-white border-b border-gray-100 shadow-sm">
        <span className="font-semibold text-gray-800 text-[15px]">
          {questionId ? "对话详情" : "新建提问"}
        </span>
        {!connected && (
          <span className="flex items-center gap-1.5 text-amber-500 text-xs bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> 连接中
          </span>
        )}
        {stage === "running" && (
          <span className="flex items-center gap-1.5 text-blue-500 text-xs bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
            <CaretRightOutlined className="text-[10px]" /> 研究中
          </span>
        )}
        {stage === "done" && (
          <span className="flex items-center gap-1.5 text-emerald-600 text-xs bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
            <CheckCircleFilled className="text-[10px]" /> 已完成
          </span>
        )}
        {stage === "error" && (
          <span className="flex items-center gap-1.5 text-red-500 text-xs bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
            <ExclamationCircleFilled className="text-[10px]" /> 出错
          </span>
        )}
        {stage === "done" && reportId && (
          <button onClick={() => navigate(`/reports/${reportId}`)}
            className="ml-auto flex items-center gap-1.5 bg-blue-500 hover:bg-blue-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors shadow-sm">
            <FileTextOutlined /> 查看报告
          </button>
        )}
      </div>

      {/* messages */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-0">
        {bubbles.length === 0 && stage === "idle" && (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 mt-16">
            <div className="mb-5">
              <AiAvatar size={64} rounded="rounded-2xl" />
            </div>
            <p className="text-lg font-semibold text-gray-800 mb-2">南芯市场研究助手</p>
            <p className="text-sm text-gray-400 leading-relaxed max-w-xs">
              输入市场、产品、竞品或技术问题，我将整合公司知识库、Market Engine 与 Web 证据生成报告。
            </p>
            <div className="flex gap-2 mt-6">
              {["AI 服务器电源管理市场有多大？", "分析 MPS 近期产品策略", "SiC 在车载电源中的采用趋势"].map(hint => (
                <button key={hint} onClick={() => { setInputText(hint); }}
                  className="text-xs text-blue-500 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-full transition-colors whitespace-nowrap">
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        {bubbles.map((b, i) => <ChatBubble key={i} role={b.role} content={b.content} />)}
        {stage === "asking" && <TypingDots />}

        {kwCard && (
          <div className="mb-4">
            <KeywordConfirmCard
              questionId={kwCard.questionId} subQuestions={kwCard.subQuestions}
              initialKeywords={kwCard.keywords} initialTier={kwCard.tier}
              initialReportType={kwCard.reportType} researchParams={kwCard.researchParams}
              onConfirm={handleConfirm} onCancel={handleCancel}
            />
          </div>
        )}

        {progressItems.length > 0 && (
          <div className="mb-4">
            <PipelineProgress items={progressItems} allDone={stage === "done"} taskId={currentTaskId} />
          </div>
        )}

        {errorMsg && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl px-4 py-3 mt-2">
            <ExclamationCircleFilled className="text-red-400 mt-0.5 shrink-0" />
            <span className="text-sm text-red-700">{errorMsg}</span>
            <button onClick={() => setErrorMsg(null)} className="ml-auto text-red-300 hover:text-red-500 text-lg leading-none">×</button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* input */}
      {stage !== "done" && (
        <div className="bg-white border-t border-gray-100 px-5 py-4 shadow-[0_-2px_12px_rgba(0,0,0,0.04)]">
          {stage === "idle" && (
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-gray-400 font-medium">档位</span>
              <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                {(["quick","normal","deep"] as Tier[]).map((t, i) => (
                  <button key={t} onClick={() => setCurrentTier(t)}
                    className={`text-xs px-3 py-1.5 font-medium transition-colors ${
                      currentTier === t
                        ? "bg-blue-500 text-white"
                        : "text-gray-500 hover:bg-gray-50"
                    } ${i > 0 ? "border-l border-gray-200" : ""}`}>
                    {t === "quick" ? "⚡ 快速" : t === "normal" ? "📋 标准" : "🔬 深度"}
                  </button>
                ))}
              </div>
              <Tooltip title="快速：公司知识库 + ME；标准：按缺口补充 Web；深度：扩大 Web 证据范围">
                <span className="w-4 h-4 rounded-full bg-gray-100 text-gray-400 text-[11px] flex items-center justify-center cursor-help font-bold">?</span>
              </Tooltip>
            </div>
          )}

          <div className="flex gap-2.5 items-end">
            <textarea
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              disabled={isDisabled}
              placeholder={
                stage === "clarifying" ? "回复补充信息（Enter 发送）..."
                : stage === "idle" ? "输入市场研究问题，Enter 发送，Shift+Enter 换行..."
                : "等待中..."
              }
              rows={2}
              className="flex-1 resize-none text-sm text-gray-800 placeholder-gray-400 bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all disabled:opacity-50"
              style={{ maxHeight: 160, overflowY: "auto" }}
            />
            <button
              onClick={handleSend}
              disabled={isDisabled || !inputText.trim()}
              className="w-12 h-12 rounded-xl flex items-center justify-center text-white transition-all shrink-0 disabled:opacity-40 disabled:cursor-not-allowed bg-gradient-to-br from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 shadow-md shadow-blue-200 active:scale-95 disabled:shadow-none">
              <SendOutlined />
            </button>
          </div>

          {stage === "clarifying" && (
            <div className="mt-2 text-right">
              <button
                onClick={() => {
                  if (currentQuestionId === null) return;
                  setBubbles(prev => [...prev, { role: "user", content: "跳过，直接继续" }]);
                  send({ type: "clarify_reply", question_id: currentQuestionId, text: "跳过" });
                }}
                className="text-xs text-blue-400 hover:text-blue-600 transition-colors">
                跳过，直接继续 →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function AskPage() {
  const navigate = useNavigate();
  const { questionId: qidParam } = useParams<{ questionId?: string }>();
  const selectedId = qidParam ? parseInt(qidParam, 10) : null;

  const token = localStorage.getItem("token") ?? "";
  const { connected, send, lastMessage } = useAskWS(token || null);

  // Per-question WS message cache so ChatPanel can replay on remount
  const wsHistoryRef = useRef<Map<number | "new", WsMsg[]>>(new Map());
  useEffect(() => {
    if (!lastMessage) return;
    const qid: number | "new" = (lastMessage as { question_id?: number }).question_id ?? "new";
    wsHistoryRef.current.set(qid, [...(wsHistoryRef.current.get(qid) ?? []), lastMessage]);
  }, [lastMessage]);

  const [questions, setQuestions] = useState<QuestionSummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  // Bumped each time "新建提问" is clicked, so repeated clicks force a fresh panel
  const [newCounter, setNewCounter] = useState(0);

  const fetchList = useCallback(() => {
    apiClient.get<QuestionSummary[]>("/api/questions").then(res => setQuestions(res.data))
      .finally(() => setLoadingList(false));
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleSidebarSelect = useCallback((qid: number) => {
    navigate(`/ask/${qid}`);
  }, [navigate]);

  const handleNewQuestion = useCallback(() => {
    navigate("/ask");
    setNewCounter(c => c + 1);
  }, [navigate]);

  const handleDeleteSession = useCallback(async (qid: number, qStatus: string) => {
    // Only a `done` question owns a report we want to preserve, so it uses the
    // session-only delete. Everything else (cancelled/failed/in-progress) has a
    // ResearchTask row referencing the question but no report — a bare question
    // delete would hit a FK violation, so use the cascading delete that clears
    // pending_docs / gate_results / task first.
    const keepReport = qStatus === "done";
    try {
      await apiClient.delete(keepReport ? `/api/questions/${qid}/session` : `/api/questions/${qid}`);
      setQuestions(prev => prev.filter(q => q.id !== qid));
      wsHistoryRef.current.delete(qid);
      if (selectedId === qid) navigate("/ask", { replace: true });
    } catch {
      // Server-side delete failed: refetch so the list reflects reality instead
      // of optimistically hiding a row that still exists.
      fetchList();
    }
  }, [selectedId, navigate, fetchList]);

  const handleQuestionCreated = useCallback((id: number) => {
    navigate(`/ask/${id}`, { replace: true });
    const msgs = wsHistoryRef.current.get("new") ?? [];
    if (msgs.length) {
      wsHistoryRef.current.set(id, [...(wsHistoryRef.current.get(id) ?? []), ...msgs]);
      wsHistoryRef.current.delete("new");
    }
    fetchList();
  }, [navigate, fetchList]);

  // Key: each distinct conversation gets its own panel instance.
  // selectedId=null uses newCounter so repeated "新建提问" still remounts.
  const panelKey = selectedId !== null ? `q-${selectedId}` : `new-${newCounter}`;

  return (
    <div className="flex h-[calc(100vh-64px)] bg-gray-50">
      {/* sidebar */}
      <div className="w-64 shrink-0 border-r border-gray-100 flex flex-col bg-white">
        {/* new button */}
        <div className="p-3 border-b border-gray-100">
          <button onClick={handleNewQuestion}
            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white text-sm font-semibold py-2.5 rounded-xl transition-all shadow-md shadow-blue-200 active:scale-[0.98]">
            <PlusOutlined /> 新建提问
          </button>
        </div>

        {/* list */}
        <div className="flex-1 overflow-y-auto">
          {loadingList ? (
            <div className="flex justify-center pt-8"><Spin size="small" /></div>
          ) : questions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
                <RobotOutlined className="text-gray-300 text-xl" />
              </div>
              <p className="text-[13px] text-gray-400 font-medium">暂无提问记录</p>
              <p className="text-xs text-gray-300 mt-1">点击上方按钮开始</p>
            </div>
          ) : (
            questions.map(q => (
              <SidebarItem key={q.id} q={q} isSelected={q.id === selectedId}
                onSelect={() => handleSidebarSelect(q.id)}
                onDelete={() => handleDeleteSession(q.id, q.status)}
              />
            ))
          )}
        </div>

        {/* connection status */}
        <div className="px-4 py-2.5 border-t border-gray-100 flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full transition-colors ${connected ? "bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.2)]" : "bg-amber-400 shadow-[0_0_0_3px_rgba(251,191,36,0.2)]"}`} />
          <span className="text-[11px] text-gray-400">{connected ? "已连接" : "连接中..."}</span>
        </div>
      </div>

      {/* chat */}
      <ChatPanel
        key={panelKey}
        questionId={selectedId}
        onQuestionCreated={handleQuestionCreated}
        connected={connected} send={send}
        lastMessage={lastMessage}
        wsHistory={wsHistoryRef.current.get(selectedId ?? "new") ?? []}
      />
    </div>
  );
}
