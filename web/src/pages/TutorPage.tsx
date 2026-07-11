import { useEffect, useRef, useState } from "react";
import { Button, Input, Segmented, Spin, Tag } from "antd";
import { BulbOutlined, RobotOutlined, SendOutlined, UserOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Source { ID: string; qtype: string; question: string; keypoint: string[]; hard_level: string }
interface Msg { role: "user" | "assistant"; content: string; sources?: Source[]; model?: string }

const starters = ["请讲解 P000001，并说明容易错在哪里", "推荐 3 道样本空间的基础题", "条件概率和全概率公式有什么区别？", "如何判断一道题该用贝叶斯公式？"];

export default function TutorPage() {
  const [search] = useSearchParams();
  const [mode, setMode] = useState(search.get("mode") === "recommend" ? "recommend" : "answer");
  const [input, setInput] = useState(search.get("prompt") || "");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages, loading]);
  async function send(value = input) {
    const text = value.trim(); if (!text || loading) return;
    setMessages(m => [...m, { role: "user", content: text }]); setInput(""); setLoading(true);
    try { const r = await apiClient.post("/api/question-bank/assistant", { message: text, mode }); setMessages(m => [...m, { role: "assistant", content: r.data.answer, sources: r.data.sources, model: r.data.model }]); }
    catch { setMessages(m => [...m, { role: "assistant", content: "抱歉，本次回答没有成功。请稍后重试，或直接输入具体题号。" }]); }
    finally { setLoading(false); }
  }
  return <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[260px_1fr]">
    <aside className="h-fit rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-5 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-teal-700 text-white"><RobotOutlined /></span><div><div className="text-sm font-extrabold text-slate-900">概率学伴 AI</div><div className="text-[11px] text-emerald-600">● 题库已连接</div></div></div><p className="mb-3 text-xs font-bold text-slate-400">回答方式</p><Segmented block value={mode} onChange={v => setMode(String(v))} options={[{ label: "讲解答疑", value: "answer" }, { label: "推荐题目", value: "recommend" }]} /><div className="mt-6 rounded-2xl bg-amber-50 p-4 text-xs leading-6 text-amber-800"><BulbOutlined className="mr-1" /> 可以直接输入题号，也可以粘贴题干。AI 会优先引用题库中的标准答案与解析。</div></aside>
    <section className="flex min-h-[calc(100vh-120px)] flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-6 py-5"><h1 className="text-lg font-extrabold text-slate-900">{mode === "answer" ? "智能答疑" : "题目推荐"}</h1><p className="mt-1 text-xs text-slate-400">基于当前 1007 道题库 · DeepSeek V4 Pro</p></header>
      <div className="flex-1 overflow-y-auto p-6 lg:p-8">
        {messages.length === 0 && <div className="mx-auto flex max-w-2xl flex-col items-center py-16 text-center"><span className="mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-teal-700 to-emerald-500 text-2xl text-white shadow-lg"><RobotOutlined /></span><h2 className="text-2xl font-black text-slate-900">把不会的题交给我</h2><p className="mt-3 text-sm leading-7 text-slate-400">我会先定位题库内容，再用适合学习的方式一步步讲解。</p><div className="mt-8 grid w-full gap-3 sm:grid-cols-2">{starters.map(s => <button key={s} onClick={() => send(s)} className="rounded-2xl border border-slate-200 p-4 text-left text-sm leading-6 text-slate-600 hover:border-teal-300 hover:bg-teal-50">{s}</button>)}</div></div>}
        <div className="space-y-6">{messages.map((m, i) => <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : "justify-start"}`}>{m.role === "assistant" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-700 text-white"><RobotOutlined /></span>}<div className={`max-w-[82%] rounded-2xl px-5 py-4 ${m.role === "user" ? "bg-teal-700 text-white" : "border border-slate-100 bg-slate-50 text-slate-700"}`}><div className="tutor-markdown text-[15px] leading-8"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{m.content}</ReactMarkdown></div>{m.sources && m.sources.length > 0 && <div className="mt-5 border-t border-slate-200 pt-4"><div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">参考题目</div><div className="flex flex-wrap gap-2">{m.sources.map(s => <Tag key={s.ID} color="cyan">{s.ID} · {s.hard_level}</Tag>)}</div></div>}{m.model && <div className="mt-3 text-[10px] text-slate-300">{m.model}</div>}</div>{m.role === "user" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-white"><UserOutlined /></span>}</div>)}</div>
        {loading && <div className="mt-6 flex items-center gap-3 text-sm text-slate-400"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-700 text-white"><RobotOutlined /></span><Spin size="small" /> 正在查找题库并组织讲解…</div>}<div ref={bottom} />
      </div>
      <footer className="border-t border-slate-100 bg-white p-5"><div className="mx-auto flex max-w-3xl items-end gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-teal-500 focus-within:ring-2 focus-within:ring-teal-100"><Input.TextArea value={input} onChange={e => setInput(e.target.value)} onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); send(); } }} autoSize={{ minRows: 1, maxRows: 5 }} bordered={false} placeholder={mode === "answer" ? "输入题号、题干或知识点…" : "描述想练习的知识点和难度…"} /><Button type="primary" shape="circle" icon={<SendOutlined />} loading={loading} onClick={() => send()} /></div><p className="mt-2 text-center text-[11px] text-slate-300">Enter 发送 · Shift + Enter 换行 · 答案请结合课堂要求判断</p></footer>
    </section>
  </div>;
}
