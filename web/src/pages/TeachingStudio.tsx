import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Popconfirm, Result, Segmented, Select, Spin, message } from "antd";
import { DeleteOutlined, DownloadOutlined, EditOutlined, HistoryOutlined, ReadOutlined, SaveOutlined, SendOutlined } from "@ant-design/icons";
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
  const [view, setView] = useState<"preview" | "edit">("preview");

  useEffect(() => {
    if (teacher) apiClient.get<Plan[]>("/api/question-bank/teaching-plans").then(response => { setPlans(response.data); setPlansError(false); }).catch(() => setPlansError(true)).finally(() => setPlansLoading(false));
  }, [teacher]);

  if (!teacher) return <Result status="403" title="教师专属功能" subTitle="学生账号可以使用智能答疑和题库练习。" />;

  function selectPlan(plan: Plan) {
    setActive(plan);
    setContent(plan.content);
    setView("preview");
    setDirty(false);
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
    try { await apiClient.delete(`/api/question-bank/teaching-plans/${plan.id}`); if (active?.id === plan.id) { setActive(null); setContent(""); setDirty(false); } try { await refreshPlans(); } catch { message.warning("方案已删除，但历史列表刷新失败"); } message.success("教学设计已删除"); } catch { message.error("删除失败，方案仍然保留"); }
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
    <div className="mb-6"><h1 className="text-2xl font-black text-slate-900">教学设计工作台</h1><p className="mt-1 text-sm text-slate-500">生成、编辑、保存和导出可复用的课堂方案</p></div>
    <div className="grid gap-6 xl:grid-cols-[350px_1fr]">
      <aside className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="mb-6 flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-50 text-lg text-teal-800"><ReadOutlined /></span><div><h2 className="font-extrabold text-slate-900">创建新方案</h2><p className="text-sm text-slate-500">填写主题，题号可选</p></div></div>
          <Form layout="vertical" initialValues={{ duration: 45 }} onFinish={submit} requiredMark={false}>
            <Form.Item name="topic" label="教学主题" rules={[{ required: true, message: "请输入教学主题" }, { max: 120, message: "教学主题请控制在 120 个字符以内" }]}><Input size="large" maxLength={120} showCount placeholder="如：随机事件与样本空间" /></Form.Item>
            <Form.Item name="duration" label="课时时长（分钟）"><InputNumber size="large" min={15} max={180} className="!w-full" /></Form.Item>
            <Form.Item name="question_ids" label="指定例题" rules={[{ validator: (_, values?: string[]) => !values?.some(value => !/^P\d{6}$/i.test(value.trim())) ? Promise.resolve() : Promise.reject(new Error("题号格式应为 P 加 6 位数字，如 P000001")) }]}><Select mode="tags" size="large" tokenSeparators={[",", "，", " "]} placeholder="输入题号，如 P000001" open={false} maxTagCount="responsive" /></Form.Item>
            <Form.Item name="objectives" label="教学目标或补充要求"><Input.TextArea rows={4} maxLength={3000} showCount placeholder="如：面向基础薄弱学生，增加互动与分层练习…" /></Form.Item>
            <Button block type="primary" size="large" htmlType="submit" loading={loading} icon={<SendOutlined />}>生成并保存</Button>
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
            <div className="flex flex-wrap gap-2"><Segmented value={view} onChange={value => setView(value as "preview" | "edit")} options={[{ label: "预览", value: "preview" }, { label: "编辑", value: "edit", icon: <EditOutlined /> }]} /><Button icon={<SaveOutlined />} loading={saving} disabled={!dirty} onClick={save}>{dirty ? "保存修改" : "已保存"}</Button><Button icon={<DownloadOutlined />} onClick={download}>导出 Markdown</Button></div>
          </div>
          {view === "edit" ? <Input.TextArea aria-label="编辑教学设计内容" value={content} onChange={event => { setContent(event.target.value); setDirty(event.target.value !== active.content); }} autoSize={{ minRows: 26 }} maxLength={50000} className="!font-mono !text-sm !leading-7" /> : <div className="teaching-markdown prose max-w-none text-[15px] leading-8 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{content}</ReactMarkdown></div>}
        </> : <div className="flex h-[560px] flex-col items-center justify-center text-center"><span className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-2xl text-slate-500"><ReadOutlined /></span><h3 className="text-lg font-extrabold text-slate-700">创建或打开一份教学设计</h3><p className="mt-2 max-w-sm text-sm leading-7 text-slate-500">生成后的方案会自动保存。你可以切换到编辑模式修改，并导出为 Markdown 文件。</p></div>}
      </section>
    </div>
  </div>;
}
