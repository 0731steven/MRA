import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Popconfirm, Result, Segmented, Select, Spin, Tag, message } from "antd";
import { DeleteOutlined, DownloadOutlined, EditOutlined, HistoryOutlined, ReadOutlined, SafetyCertificateOutlined, SaveOutlined, SendOutlined, WarningOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Plan {
  id: number;
  title: string;
  topic: string;
  duration: number;
  question_ids: string[];
  content: string;
  model?: string;
  updated_at?: string;
  layers?: Record<"易" | "中" | "难", string[]>;
  insights?: Insights;
}

interface Insights {
  keypoints: string[];
  prerequisites: Record<string, string[]>;
  layers: Record<"易" | "中" | "难", string[]>;
  diagnostics: { attempts: number; verdicts: Record<string, number>; error_types: { name: string; count: number }[] };
  warnings: { severity: "high" | "medium" | "low"; title: string; detail: string }[];
}

export default function TeachingStudio() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const teacher = user?.role === "teacher";
  const [plans, setPlans] = useState<Plan[]>([]);
  const [active, setActive] = useState<Plan | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [view, setView] = useState<"preview" | "insights" | "edit">("preview");
  const [insights, setInsights] = useState<Insights | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  useEffect(() => {
    if (teacher) apiClient.get<Plan[]>("/api/question-bank/teaching-plans").then(response => { setPlans(response.data); setPlansError(false); }).catch(() => setPlansError(true)).finally(() => setPlansLoading(false));
  }, [teacher]);

  if (!teacher) return <Result status="403" title="教师专属功能" subTitle="学生账号可以使用智能答疑和题库练习。" />;

  function selectPlan(plan: Plan) {
    setActive(plan);
    setContent(plan.content);
    setView("preview");
    setDirty(false);
    setInsights(null);
    void loadInsights(plan);
  }

  async function loadInsights(plan: Plan) {
    setInsightsLoading(true);
    try {
      const response = await apiClient.get<Insights>("/api/question-bank/teaching-insights", { params: { topic: plan.topic, question_ids: plan.question_ids.join(",") } });
      setInsights(response.data);
    } catch { setInsights(null); } finally { setInsightsLoading(false); }
  }

  async function refreshPlans(preferredId?: number) {
    try { const response = await apiClient.get<Plan[]>("/api/question-bank/teaching-plans"); setPlans(response.data); setPlansError(false); if (preferredId) { const plan = response.data.find(item => item.id === preferredId); if (plan) selectPlan(plan); } } catch (error) { setPlansError(true); throw error; }
  }

  async function submit(values: { topic: string; duration: number; objectives?: string; question_ids?: string[] }) {
    setLoading(true);
    try {
      const response = await apiClient.post<Plan>("/api/question-bank/teaching-plan", values);
      setActive(response.data);
      setContent(response.data.content);
      setView("preview");
      setDirty(false);
      setInsights(response.data.insights || null);
      try { await refreshPlans(response.data.id); } catch { message.warning("方案已生成，但历史列表刷新失败"); }
      message.success("教学设计已生成并保存");
    } catch { message.error("教学设计生成失败，请保留当前表单并稍后重试"); } finally { setLoading(false); }
  }

  async function save() {
    if (!active) return;
    setSaving(true);
    try {
      await apiClient.put(`/api/question-bank/teaching-plans/${active.id}`, { title: active.title, content });
      try { await refreshPlans(active.id); } catch { message.warning("修改已保存，但历史列表刷新失败"); }
      setDirty(false);
      message.success("修改已保存");
    } catch { message.error("保存失败，当前编辑内容仍保留在页面中"); } finally { setSaving(false); }
  }

  async function remove(plan: Plan) {
    try { await apiClient.delete(`/api/question-bank/teaching-plans/${plan.id}`); if (active?.id === plan.id) { setActive(null); setContent(""); setDirty(false); setInsights(null); } try { await refreshPlans(); } catch { message.warning("方案已删除，但历史列表刷新失败"); } message.success("教学设计已删除"); } catch { message.error("删除失败，方案仍然保留"); }
  }

  function download() {
    if (!active) return;
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${(active.topic || "教学设计").replace(/[\\/:*?"<>|]/g, "-")}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <div>
    <div className="mb-6"><h1 className="text-2xl font-black text-slate-900">分层教学包工作台</h1><p className="mt-1 text-sm text-slate-500">生成学习单、分层练习、课堂检测与认知断层预警</p></div>
    <div className="grid gap-6 xl:grid-cols-[350px_1fr]">
      <aside className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="mb-6 flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-50 text-lg text-teal-800"><ReadOutlined /></span><div><h2 className="font-extrabold text-slate-900">创建新方案</h2><p className="text-sm text-slate-500">填写主题，题号可选</p></div></div>
          <Form layout="vertical" initialValues={{ duration: 45 }} onFinish={submit} requiredMark={false}>
            <Form.Item name="topic" label="教学主题" rules={[{ required: true, message: "请输入教学主题" }, { max: 120, message: "教学主题请控制在 120 个字符以内" }]}><Input size="large" maxLength={120} showCount placeholder="如：随机事件与样本空间" /></Form.Item>
            <Form.Item name="duration" label="课时时长（分钟）"><InputNumber size="large" min={15} max={180} className="!w-full" /></Form.Item>
            <Form.Item name="question_ids" label="指定例题" rules={[{ validator: (_, values?: string[]) => !values?.some(value => !/^P\d{6}$/i.test(value.trim())) ? Promise.resolve() : Promise.reject(new Error("题号格式应为 P 加 6 位数字，如 P000001")) }]}><Select mode="tags" size="large" tokenSeparators={[",", "，", " "]} placeholder="输入题号，如 P000001" open={false} maxTagCount="responsive" /></Form.Item>
            <Form.Item name="objectives" label="教学目标或补充要求"><Input.TextArea rows={4} maxLength={3000} showCount placeholder="如：面向基础薄弱学生，增加互动与分层练习…" /></Form.Item>
            <Button block type="primary" size="large" htmlType="submit" loading={loading} icon={<SendOutlined />}>生成完整教学包</Button>
          </Form>
          <Alert className="mt-5" type="info" showIcon message="方案只引用当前题库中的题目，并自动进入历史记录。" />
        </section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="mb-4 flex items-center gap-2 font-extrabold text-slate-800"><HistoryOutlined className="text-teal-700" />历史方案</div>
          <div className="max-h-80 space-y-2 overflow-y-auto">
            {plansLoading ? <div className="py-6 text-center"><Spin size="small" /></div> : plansError && plans.length === 0 ? <Alert type="error" showIcon message="历史方案加载失败" action={<Button size="small" onClick={() => { setPlansLoading(true); setPlansError(false); refreshPlans().catch(() => setPlansError(true)).finally(() => setPlansLoading(false)); }}>重试</Button>} /> : plans.length === 0 ? <p className="py-6 text-center text-sm text-slate-500">暂无已保存方案，先创建第一份课堂方案</p> : plans.map(plan => { const selected = active?.id === plan.id; return <div key={plan.id} className={`group flex items-center rounded-xl border p-2 ${selected ? "border-teal-200 bg-teal-50" : "border-slate-100 hover:bg-slate-50"}`}><button className="min-w-0 flex-1 rounded-lg p-1 text-left" onClick={() => selectPlan(plan)} aria-current={selected ? "true" : undefined}><span className={`block truncate text-sm font-bold ${selected ? "text-teal-950" : "text-slate-700"}`}>{plan.title}</span><span className={`mt-1 block text-sm ${selected ? "text-teal-800" : "text-slate-500"}`}>{plan.question_ids.length} 道题 · {plan.duration} 分钟</span></button><Popconfirm title="删除这份方案？" onConfirm={() => remove(plan)}><Button aria-label={`删除方案：${plan.title}`} type="text" danger size="small" icon={<DeleteOutlined />} /></Popconfirm></div>; })}
          </div>
        </section>
      </aside>
      <section className="min-h-[700px] rounded-2xl border border-slate-200 bg-white p-6 lg:p-9">
        {loading ? <div className="flex h-96 flex-col items-center justify-center gap-4 text-sm text-slate-500"><Spin size="large" />正在检索题目并设计课堂流程…</div> : active ? <>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-5">
            <div className="min-w-0"><h2 className="truncate text-xl font-black text-slate-900">{active.title}</h2><div className="mt-2 flex flex-wrap gap-2">{active.question_ids.map(id => <Button size="small" key={id} onClick={() => navigate(`/questions?query=${id}`)}>{id}</Button>)}</div></div>
            <div className="flex flex-wrap gap-2"><Segmented value={view} onChange={value => setView(value as "preview" | "insights" | "edit")} options={[{ label: "教学包", value: "preview" }, { label: "断层预警", value: "insights", icon: <WarningOutlined /> }, { label: "编辑", value: "edit", icon: <EditOutlined /> }]} /><Button icon={<SaveOutlined />} loading={saving} disabled={!dirty} onClick={save}>{dirty ? "保存修改" : "已保存"}</Button><Button icon={<DownloadOutlined />} onClick={download}>导出 Markdown</Button></div>
          </div>
          {view === "edit" ? <Input.TextArea aria-label="编辑教学设计内容" value={content} onChange={event => { setContent(event.target.value); setDirty(event.target.value !== active.content); }} autoSize={{ minRows: 26 }} maxLength={50000} className="!font-mono !text-sm !leading-7" /> : view === "insights" ? <InsightsPanel data={insights} loading={insightsLoading} onRetry={() => loadInsights(active)} /> : <div className="teaching-markdown prose max-w-none text-[15px] leading-8 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{content}</ReactMarkdown></div>}
        </> : <div className="flex h-[560px] flex-col items-center justify-center text-center"><span className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-2xl text-slate-500"><ReadOutlined /></span><h3 className="text-lg font-extrabold text-slate-700">创建或打开一份教学设计</h3><p className="mt-2 max-w-sm text-sm leading-7 text-slate-500">生成后的方案会自动保存。你可以切换到编辑模式修改，并导出为 Markdown 文件。</p></div>}
      </section>
    </div>
  </div>;
}

function InsightsPanel({ data, loading, onRetry }: { data: Insights | null; loading: boolean; onRetry: () => void }) {
  if (loading) return <div className="flex min-h-80 items-center justify-center"><Spin tip="正在汇总题库覆盖与历史作答…"><div className="h-16 w-64" /></Spin></div>;
  if (!data) return <Alert type="error" showIcon message="预警报告加载失败" description="教学包仍可正常使用，你可以单独重新生成这份聚合报告。" action={<Button size="small" onClick={onRetry}>重试</Button>} />;
  const riskAttempts = (data.diagnostics.verdicts.incorrect || 0) + (data.diagnostics.verdicts.partial || 0);
  return <div>
    <div className="grid overflow-hidden rounded-2xl border border-slate-200 sm:grid-cols-3 sm:divide-x sm:divide-slate-200">
      <Metric label="覆盖知识点" value={data.keypoints.length} note="来自当前教学包题目" />
      <Metric label="历史诊断证据" value={data.diagnostics.attempts} note="仅展示匿名聚合结果" />
      <Metric label="未完全正确" value={riskAttempts} note="错误与部分正确作答" />
    </div>
    <section className="mt-6" aria-labelledby="layer-heading"><div className="mb-3"><h3 id="layer-heading" className="text-lg font-extrabold text-slate-900">分层覆盖检查</h3><p className="mt-1 text-sm text-slate-600">每层题目都来自当前 1007 道课程语料。</p></div><div className="divide-y divide-slate-100 border-y border-slate-200">{(["易", "中", "难"] as const).map(level => <div key={level} className="flex flex-wrap items-center gap-3 py-4"><Tag color={level === "易" ? "green" : level === "中" ? "orange" : "red"}>{level === "易" ? "基础层" : level === "中" ? "提升层" : "拓展层"}</Tag><div className="flex flex-1 flex-wrap gap-2">{data.layers[level].length ? data.layers[level].map(id => <span key={id} className="rounded-lg bg-slate-100 px-2.5 py-1 text-sm font-semibold text-slate-700">{id}</span>) : <span className="text-sm text-slate-500">当前无对应题目</span>}</div><span className="text-sm font-bold text-slate-500">{data.layers[level].length} 题</span></div>)}</div></section>
    <section className="mt-7" aria-labelledby="risk-heading"><h3 id="risk-heading" className="flex items-center gap-2 text-lg font-extrabold text-slate-900"><SafetyCertificateOutlined className="text-teal-700" />认知断层预警</h3><p className="mt-1 text-sm text-slate-600">综合题目难度覆盖、知识点密度与匿名历史诊断生成。</p>{data.warnings.length === 0 ? <Alert className="mt-4" type="success" showIcon message="当前教学包未发现明显结构性风险" /> : <div className="mt-4 divide-y divide-slate-100 border-y border-slate-200">{data.warnings.map((item, index) => <article key={`${item.title}-${index}`} className="flex gap-4 py-4"><span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${item.severity === "high" ? "bg-rose-100 text-rose-700" : item.severity === "medium" ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700"}`}><WarningOutlined /></span><div><div className="flex flex-wrap items-center gap-2"><h4 className="font-extrabold text-slate-800">{item.title}</h4><Tag color={item.severity === "high" ? "red" : item.severity === "medium" ? "orange" : "blue"}>{item.severity === "high" ? "高风险" : item.severity === "medium" ? "需关注" : "提示"}</Tag></div><p className="mt-1.5 text-sm leading-6 text-slate-600">{item.detail}</p></div></article>)}</div>}</section>
    {Object.keys(data.prerequisites).length > 0 && <section className="mt-7"><h3 className="text-lg font-extrabold text-slate-900">前置知识链</h3><div className="mt-3 divide-y divide-slate-100 border-y border-slate-200">{Object.entries(data.prerequisites).map(([target, prerequisites]) => <div key={target} className="flex flex-wrap items-center gap-2 py-3 text-sm"><span className="font-bold text-slate-700">{prerequisites.join("、")}</span><span className="text-slate-400">→</span><span className="font-extrabold text-teal-800">{target}</span></div>)}</div></section>}
  </div>;
}

function Metric({ label, value, note }: { label: string; value: number; note: string }) {
  return <div className="p-5"><p className="text-sm font-semibold text-slate-500">{label}</p><p className="mt-1 text-3xl font-black text-slate-900">{value}</p><p className="mt-1 text-sm text-slate-500">{note}</p></div>;
}
