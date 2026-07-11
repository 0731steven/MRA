import { useEffect, useRef, useState } from "react";
import { Button, Input, Popconfirm, Segmented, Spin, Tag, message as toast } from "antd";
import { BulbOutlined, DeleteOutlined, PlusOutlined, RobotOutlined, SendOutlined, UserOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Source { ID: string; qtype: string; question: string; keypoint: string[]; hard_level: string }
interface Msg { id?: number; role: "user" | "assistant"; content: string; sources?: Source[]; model?: string }
interface Session { id: number; title: string; mode: string; created_at: string; updated_at: string }

const starters = ["请讲解 P000001，并说明容易错在哪里", "推荐 3 道样本空间的基础题", "条件概率和全概率公式有什么区别？", "如何判断一道题该用贝叶斯公式？"];

export default function TutorPage() {
  const [search] = useSearchParams();
  const initialPrompt = search.get("prompt") || "";
  const [mode, setMode] = useState(search.get("mode") === "recommend" ? "recommend" : "answer");
  const [input, setInput] = useState(initialPrompt);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get<Session[]>("/api/question-bank/sessions")
      .then(async res => {
        setSessions(res.data);
        if (!initialPrompt && res.data.length) await openSession(res.data[0].id);
      })
      .finally(() => setHistoryLoading(false));
  // The initial prompt intentionally controls whether the latest session reopens.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages, loading]);

  async function refreshSessions() {
    const res = await apiClient.get<Session[]>("/api/question-bank/sessions");
    setSessions(res.data);
  }

  async function openSession(id: number) {
    if (loading) return;
    setHistoryLoading(true);
    try {
      const res = await apiClient.get<{ session: Session; messages: Msg[] }>(`/api/question-bank/sessions/${id}/messages`);
      setActiveSession(id);
      setMode(res.data.session.mode === "recommend" ? "recommend" : "answer");
      setMessages(res.data.messages);
    } finally { setHistoryLoading(false); }
  }

  function newChat() {
    if (loading) return;
    setActiveSession(null);
    setMessages([]);
    setInput("");
  }

  async function deleteSession(id: number) {
    await apiClient.delete(`/api/question-bank/sessions/${id}`);
    const remaining = sessions.filter(item => item.id !== id);
    setSessions(remaining);
    if (activeSession === id) {
      setActiveSession(null);
      setMessages([]);
      if (remaining.length) await openSession(remaining[0].id);
    }
    toast.success("会话已删除");
  }

  async function send(value = input) {
    const text = value.trim();
    if (!text || loading) return;
    setMessages(current => [...current, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const response = await apiClient.post("/api/question-bank/assistant", {
        message: text,
        mode,
        session_id: activeSession,
      });
      setActiveSession(response.data.session_id);
      setMessages(current => [...current, {
        role: "assistant",
        content: response.data.answer,
        sources: response.data.sources,
        model: response.data.model,
      }]);
      await refreshSessions();
    } catch {
      setMessages(current => [...current, { role: "assistant", content: "抱歉，本次回答没有成功。请稍后重试，或直接输入具体题号。" }]);
    } finally { setLoading(false); }
  }

  return <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[280px_1fr]">
    <aside className="flex h-[calc(100vh-120px)] flex-col rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-5 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-teal-700 text-white"><RobotOutlined /></span><div><div className="text-sm font-extrabold text-slate-900">概率学伴 AI</div><div className="text-[11px] text-emerald-600">● 题库与记忆已连接</div></div></div>
      <Button type="primary" block icon={<PlusOutlined />} onClick={newChat} className="!mb-5 !font-bold">新建对话</Button>
      <p className="mb-2 text-xs font-bold text-slate-400">回答方式</p>
      <Segmented block value={mode} onChange={value => setMode(String(value))} options={[{ label: "讲解答疑", value: "answer" }, { label: "推荐题目", value: "recommend" }]} />
      <div className="mt-5 flex min-h-0 flex-1 flex-col border-t border-slate-100 pt-5">
        <p className="mb-3 text-xs font-bold text-slate-400">历史会话</p>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {historyLoading && !sessions.length ? <div className="py-6 text-center"><Spin size="small" /></div> : sessions.length === 0 ? <p className="py-5 text-center text-xs text-slate-300">暂无历史会话</p> : sessions.map(item => <button key={item.id} onClick={() => openSession(item.id)} className={`group flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left transition ${activeSession === item.id ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:bg-slate-50"}`}><span className="min-w-0 flex-1 truncate text-xs font-semibold">{item.title}</span><Popconfirm title="删除此会话？" okText="删除" cancelText="取消" onConfirm={event => { event?.stopPropagation(); deleteSession(item.id); }}><span onClick={event => event.stopPropagation()} className="hidden rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-500 group-hover:inline-flex"><DeleteOutlined /></span></Popconfirm></button>)}
        </div>
      </div>
      <div className="mt-4 rounded-2xl bg-amber-50 p-3 text-[11px] leading-5 text-amber-800"><BulbOutlined className="mr-1" /> 最近 20 条消息会用于理解追问；全部会话会在刷新后保留。</div>
    </aside>
    <section className="flex h-[calc(100vh-120px)] flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-6 py-5"><h1 className="text-lg font-extrabold text-slate-900">{mode === "answer" ? "智能答疑" : "题目推荐"}</h1><p className="mt-1 text-xs text-slate-400">题库溯源 · 连续对话 · DeepSeek V4 Pro</p></header>
      <div className="flex-1 overflow-y-auto p-6 lg:p-8">
        {historyLoading && activeSession ? <div className="flex h-full items-center justify-center"><Spin /></div> : messages.length === 0 && <div className="mx-auto flex max-w-2xl flex-col items-center py-16 text-center"><span className="mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-teal-700 to-emerald-500 text-2xl text-white shadow-lg"><RobotOutlined /></span><h2 className="text-2xl font-black text-slate-900">把不会的题交给我</h2><p className="mt-3 text-sm leading-7 text-slate-400">我会记住当前会话，支持围绕同一道题连续追问。</p><div className="mt-8 grid w-full gap-3 sm:grid-cols-2">{starters.map(starter => <button key={starter} onClick={() => send(starter)} className="rounded-2xl border border-slate-200 p-4 text-left text-sm leading-6 text-slate-600 hover:border-teal-300 hover:bg-teal-50">{starter}</button>)}</div></div>}
        <div className="space-y-6">{messages.map((item, index) => <div key={item.id || index} className={`flex gap-3 ${item.role === "user" ? "justify-end" : "justify-start"}`}>{item.role === "assistant" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-700 text-white"><RobotOutlined /></span>}<div className={`max-w-[82%] rounded-2xl px-5 py-4 ${item.role === "user" ? "bg-teal-700 text-white" : "border border-slate-100 bg-slate-50 text-slate-700"}`}><div className="tutor-markdown text-[15px] leading-8"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{item.content}</ReactMarkdown></div>{item.sources && item.sources.length > 0 && <div className="mt-5 border-t border-slate-200 pt-4"><div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">参考题目</div><div className="flex flex-wrap gap-2">{item.sources.map(source => <Tag key={source.ID} color="cyan">{source.ID} · {source.hard_level}</Tag>)}</div></div>}{item.model && <div className="mt-3 text-[10px] text-slate-300">{item.model}</div>}</div>{item.role === "user" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-white"><UserOutlined /></span>}</div>)}</div>
        {loading && <div className="mt-6 flex items-center gap-3 text-sm text-slate-400"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-700 text-white"><RobotOutlined /></span><Spin size="small" /> 正在结合题库与对话上下文思考…</div>}<div ref={bottom} />
      </div>
      <footer className="border-t border-slate-100 bg-white p-5"><div className="mx-auto flex max-w-3xl items-end gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-teal-500 focus-within:ring-2 focus-within:ring-teal-100"><Input.TextArea value={input} onChange={event => setInput(event.target.value)} onPressEnter={event => { if (!event.shiftKey) { event.preventDefault(); send(); } }} autoSize={{ minRows: 1, maxRows: 5 }} bordered={false} placeholder={mode === "answer" ? "继续追问，或输入新的题号与知识点…" : "描述想练习的知识点和难度…"} /><Button type="primary" shape="circle" icon={<SendOutlined />} loading={loading} onClick={() => send()} /></div><p className="mt-2 text-center text-[11px] text-slate-300">会话自动保存 · Enter 发送 · Shift + Enter 换行</p></footer>
    </section>
  </div>;
}
