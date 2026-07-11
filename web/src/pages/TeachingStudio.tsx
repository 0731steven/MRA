import { useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Result, Select, Spin, Tag } from "antd";
import { ReadOutlined, SendOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

export default function TeachingStudio() {
  const { user } = useAuth();
  const teacher = user?.role === "teacher" || user?.role === "admin";
  const [content, setContent] = useState(""); const [ids, setIds] = useState<string[]>([]); const [loading, setLoading] = useState(false);
  if (!teacher) return <Result status="403" title="教师专属功能" subTitle="学生账号可以使用智能答疑和题库练习。" />;
  async function submit(values: { topic: string; duration: number; objectives?: string; question_ids?: string[] }) { setLoading(true); setContent(""); try { const r = await apiClient.post("/api/question-bank/teaching-plan", values); setContent(r.data.content); setIds(r.data.question_ids); } finally { setLoading(false); } }
  return <div><div className="mb-6"><h1 className="text-2xl font-black text-slate-900">教学设计工作台</h1><p className="mt-1 text-sm text-slate-400">基于题库例题，生成可直接调整的课堂教学方案</p></div><div className="grid gap-6 lg:grid-cols-[380px_1fr]">
    <section className="h-fit rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><div className="mb-6 flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-teal-50 text-lg text-teal-700"><ReadOutlined /></span><div><h2 className="font-extrabold text-slate-900">课程设置</h2><p className="text-xs text-slate-400">填写主题，题号可选</p></div></div><Form layout="vertical" initialValues={{ duration: 45 }} onFinish={submit} requiredMark={false}><Form.Item name="topic" label="教学主题" rules={[{ required: true, message: "请输入教学主题" }]}><Input size="large" placeholder="如：随机事件与样本空间" /></Form.Item><Form.Item name="duration" label="课时时长（分钟）"><InputNumber size="large" min={15} max={180} className="!w-full" /></Form.Item><Form.Item name="question_ids" label="指定例题"><Select mode="tags" size="large" tokenSeparators={[",", "，", " "]} placeholder="输入题号，如 P000001" open={false} /></Form.Item><Form.Item name="objectives" label="教学目标或补充要求"><Input.TextArea rows={5} placeholder="如：面向基础薄弱学生，增加课堂互动与分层练习…" /></Form.Item><Button block type="primary" size="large" htmlType="submit" loading={loading} icon={<SendOutlined />}>生成教学设计</Button></Form><Alert className="mt-5" type="info" showIcon message="生成内容只使用当前题库中的例题，并在方案中标明题号。" /></section>
    <section className="min-h-[680px] rounded-3xl border border-slate-200 bg-white p-8 shadow-sm lg:p-10">{loading ? <div className="flex h-96 flex-col items-center justify-center gap-4 text-sm text-slate-400"><Spin size="large" />正在检索题目并设计课堂流程…</div> : content ? <><div className="mb-6 flex flex-wrap items-center gap-2 border-b border-slate-100 pb-5"><span className="mr-2 text-xs font-bold text-slate-400">使用题目</span>{ids.map(id => <Tag color="cyan" key={id}>{id}</Tag>)}</div><div className="teaching-markdown prose max-w-none text-[15px] leading-8 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{content}</ReactMarkdown></div></> : <div className="flex h-[560px] flex-col items-center justify-center text-center"><span className="mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-slate-100 text-2xl text-slate-400"><ReadOutlined /></span><h3 className="text-lg font-extrabold text-slate-700">教学设计将在这里生成</h3><p className="mt-2 max-w-sm text-sm leading-7 text-slate-400">填写左侧课程信息。系统会选择适合的导入题、例题与分层练习，并安排完整课堂节奏。</p></div>}</section>
  </div></div>;
}
