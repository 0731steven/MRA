import { useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Input, Popconfirm, Segmented, Spin, Tag, message as toast } from "antd";
import { BulbOutlined, DeleteOutlined, EyeOutlined, PlusOutlined, RobotOutlined, SendOutlined, StopOutlined, UserOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Source { ID: string; qtype: string; question: string; keypoint: string[]; hard_level: string }
interface Msg { id?: number; role: "user" | "assistant"; content: string; sources?: Source[]; model?: string }
interface Session { id: number; title: string; mode: string; created_at: string; updated_at: string }
interface QuestionDetail extends Source { answer?: string; explanation?: string }

const guidanceOptions = [
  { label: "只给提示", value: "hint" },
  { label: "检查思路", value: "check" },
  { label: "分步引导", value: "step" },
  { label: "完整解析", value: "full" },
];

const starters = ["请讲解 P000001，并说明容易错在哪里", "推荐 3 道样本空间的基础题", "条件概率和全概率公式有什么区别？", "如何判断一道题该用贝叶斯公式？"];

export default function TutorPage() {
  const [search] = useSearchParams();
  const initialPrompt = search.get("prompt") || "";
  const [mode, setMode] = useState(search.get("mode") === "recommend" ? "recommend" : "answer");
  const [guidanceMode, setGuidanceMode] = useState("step");
  const [input, setInput] = useState(initialPrompt);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [selected, setSelected] = useState<QuestionDetail | null>(null);
  const [showAnswer, setShowAnswer] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const requestController = useRef<AbortController | null>(null);

  useEffect(() => {
    apiClient.get<Session[]>("/api/question-bank/sessions")
      .then(async res => {
        setSessions(res.data);
        if (!initialPrompt && res.data.length) await openSession(res.data[0].id);
      })
      .catch(() => setHistoryError(true))
      .finally(() => setHistoryLoading(false));
  // The initial prompt intentionally controls whether the latest session reopens.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages, loading]);

  async function refreshSessions() {
    try { const res = await apiClient.get<Session[]>("/api/question-bank/sessions"); setSessions(res.data); setHistoryError(false); } catch { setHistoryError(true); }
  }

  async function openSession(id: number) {
    if (loading) return;
    setHistoryLoading(true);
    try {
      const res = await apiClient.get<{ session: Session; messages: Msg[] }>(`/api/question-bank/sessions/${id}/messages`);
      setActiveSession(id);
      setMode(res.data.session.mode === "recommend" ? "recommend" : "answer");
      setMessages(res.data.messages);
      setHistoryError(false);
    } catch { toast.error("会话加载失败，请稍后重试"); } finally { setHistoryLoading(false); }
  }

  function newChat() {
    if (loading) return;
    setActiveSession(null);
    setMessages([]);
    setInput("");
  }

  async function openSource(id: string) {
    try { const response = await apiClient.get<QuestionDetail>(`/api/question-bank/questions/${id}`); setSelected(response.data); setShowAnswer(false); } catch { toast.error("题目详情加载失败，请稍后重试"); }
  }

  async function deleteSession(id: number) {
    try { await apiClient.delete(`/api/question-bank/sessions/${id}`); const remaining = sessions.filter(item => item.id !== id); setSessions(remaining); if (activeSession === id) { setActiveSession(null); setMessages([]); if (remaining.length) await openSession(remaining[0].id); } toast.success("会话已删除"); } catch { toast.error("删除失败，会话仍然保留"); }
  }

  async function send(value = input) {
    const text = value.trim();
    if (!text || loading) return;
    setMessages(current => [...current, { role: "user", content: text }, { role: "assistant", content: "" }]);
    setInput("");
    setLoading(true);
    const controller = new AbortController();
    requestController.current = controller;
    try {
      const token = localStorage.getItem("token");
      const response = await fetch("/api/question-bank/assistant/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ message: text, mode, guidance_mode: guidanceMode, session_id: activeSession }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error("stream failed");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const applyEvent = (line: string) => {
        if (!line.trim()) return;
        const packet = JSON.parse(line) as { event: string; data: unknown };
        if (packet.event === "meta") {
          const data = packet.data as { session_id: number; sources: Source[] };
          setActiveSession(data.session_id);
          setMessages(current => current.map((item, index) => index === current.length - 1 ? { ...item, sources: data.sources } : item));
        } else if (packet.event === "delta") {
          const delta = String(packet.data || "");
          setMessages(current => current.map((item, index) => index === current.length - 1 ? { ...item, content: item.content + delta } : item));
        } else if (packet.event === "done") {
          const data = packet.data as { model: string };
          setMessages(current => current.map((item, index) => index === current.length - 1 ? { ...item, model: data.model } : item));
        }
      };
      while (true) {
        const { value: chunk, done } = await reader.read();
        buffer += decoder.decode(chunk || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        lines.forEach(applyEvent);
        if (done) break;
      }
      applyEvent(buffer);
      await refreshSessions();
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        setMessages(current => current.map((item, index) => index === current.length - 1 && !item.content ? { ...item, content: "已停止本次生成。" } : item));
      } else {
        setMessages(current => current.map((item, index) => index === current.length - 1 && !item.content ? { ...item, content: "抱歉，本次回答没有成功。请稍后重试，或直接输入具体题号。" } : item));
      }
    } finally { requestController.current = null; setLoading(false); }
  }

  return <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[280px_1fr]">
    <aside className="tutor-sidebar flex h-auto flex-col rounded-2xl border p-5 lg:h-[calc(100vh-132px)]">
      <div className="mb-5 flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-600 text-white"><RobotOutlined /></span><div><div className="tutor-sidebar-title text-sm font-extrabold">概率统计教学助手</div><div className={`text-sm ${historyError ? "text-rose-300" : "text-emerald-300"}`}>{historyError ? "会话连接异常" : "题库与会话已连接"}</div></div></div>
      <Button type="primary" block icon={<PlusOutlined />} onClick={newChat} className="!mb-5 !font-bold">新建对话</Button>
      <p className="tutor-sidebar-label mb-2 text-sm font-bold">回答方式</p>
      <Segmented block value={mode} onChange={value => setMode(String(value))} options={[{ label: "讲解答疑", value: "answer" }, { label: "推荐题目", value: "recommend" }]} />
      {mode === "answer" && <><p className="tutor-sidebar-label mb-2 mt-4 text-sm font-bold">辅导方式</p><Segmented vertical block value={guidanceMode} onChange={value => setGuidanceMode(String(value))} options={guidanceOptions} /></>}
      <div className="mt-5 flex min-h-0 flex-col border-t border-slate-700 pt-5 lg:flex-1">
        <p className="tutor-sidebar-label mb-3 text-sm font-bold">历史会话</p>
        <div className="max-h-48 min-h-0 space-y-1 overflow-y-auto pr-1 lg:max-h-none lg:flex-1">
          {historyLoading && !sessions.length ? <div className="py-6 text-center"><Spin size="small" /></div> : historyError && !sessions.length ? <Alert type="error" showIcon message="历史会话加载失败" action={<Button size="small" onClick={refreshSessions}>重试</Button>} /> : sessions.length === 0 ? <p className="py-5 text-center text-sm text-slate-400">暂无历史会话</p> : sessions.map(item => <div key={item.id} className={`group flex items-center gap-1 rounded-xl px-1.5 transition ${activeSession === item.id ? "bg-teal-700 text-white" : "text-slate-300 hover:bg-slate-800"}`}><button onClick={() => openSession(item.id)} className="min-w-0 flex-1 truncate rounded-lg px-2 py-2.5 text-left text-sm font-semibold" aria-current={activeSession === item.id ? "true" : undefined}>{item.title}</button><Popconfirm title="删除此会话？" okText="删除" cancelText="取消" onConfirm={() => deleteSession(item.id)}><Button aria-label={`删除会话：${item.title}`} type="text" danger size="small" icon={<DeleteOutlined />} /></Popconfirm></div>)}
        </div>
      </div>
      <div className="mt-4 rounded-xl bg-slate-800 p-3 text-sm leading-5 text-slate-300"><BulbOutlined className="mr-1 text-teal-300" /> 最近 20 条消息会用于理解追问；全部会话会在刷新后保留。</div>
    </aside>
    <section className="flex h-[calc(100dvh-168px)] min-h-[590px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white lg:h-[calc(100vh-132px)] lg:min-h-[640px]">
      <header className="border-b border-slate-100 px-5 py-5 sm:px-6"><div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-lg font-extrabold text-slate-900">{mode === "answer" ? "智能答疑" : "题目推荐"}</h1><p className="mt-1 text-sm text-slate-500">题库溯源 · 增量回答 · {mode === "answer" ? guidanceOptions.find(item => item.value === guidanceMode)?.label : "智能筛选"}</p></div><span className="rounded-full bg-teal-50 px-3 py-1.5 text-sm font-bold text-teal-800">苏格拉底式引导</span></div></header>
      <div className="flex-1 overflow-y-auto p-5 lg:p-8" role="log" aria-live="polite" aria-label="答疑消息">
        {historyLoading && activeSession ? <div className="flex h-full items-center justify-center"><Spin /></div> : messages.length === 0 && <div className="mx-auto flex max-w-2xl flex-col items-center py-12 text-center"><span className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-700 text-2xl text-white" aria-hidden="true"><RobotOutlined /></span><h2 className="text-2xl font-black text-slate-900">把不会的题交给我</h2><p className="mt-3 text-[15px] leading-7 text-slate-600">我会记住当前会话，支持围绕同一道题连续追问。</p><div className="mt-7 grid w-full gap-3 sm:grid-cols-2">{starters.map(starter => <button key={starter} onClick={() => send(starter)} className="rounded-xl border border-slate-200 p-4 text-left text-sm leading-6 text-slate-700 transition hover:border-teal-300 hover:bg-teal-50">{starter}</button>)}</div></div>}
        <div className="space-y-6">{messages.map((item, index) => <div key={item.id || index} className={`flex gap-3 ${item.role === "user" ? "justify-end" : "justify-start"}`}>{item.role === "assistant" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-700 text-white" aria-hidden="true"><RobotOutlined /></span>}<div className={`max-w-[86%] rounded-2xl px-4 py-3.5 sm:max-w-[82%] sm:px-5 sm:py-4 ${item.role === "user" ? "bg-teal-700 text-white" : "bg-slate-50 text-slate-700"}`}>{item.role === "assistant" && !item.content ? <div className="flex items-center gap-2 py-1 text-sm text-slate-500"><Spin size="small" />正在检索题库并组织引导…</div> : <div className="tutor-markdown text-[15px] leading-8"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{item.content}</ReactMarkdown></div>}{item.sources && item.sources.length > 0 && <div className="mt-5 border-t border-slate-200 pt-4"><div className="mb-3 text-sm font-bold text-slate-600">参考题目 · 点击查看</div><div className="grid gap-2 sm:grid-cols-2">{item.sources.map(source => <button key={source.ID} onClick={() => openSource(source.ID)} className="rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-teal-300 hover:bg-teal-50"><div className="flex items-center justify-between"><span className="text-sm font-extrabold text-teal-800">{source.ID}</span><Tag color="cyan" className="!mr-0">{source.hard_level}</Tag></div><p className="mt-2 line-clamp-2 text-sm leading-5 text-slate-600">{source.question}</p></button>)}</div></div>}{item.model && <div className="mt-3 text-sm text-slate-500">回答模型：{item.model}</div>}</div>{item.role === "user" && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-white" aria-hidden="true"><UserOutlined /></span>}</div>)}</div>
        <div ref={bottom} />
      </div>
      <footer className="border-t border-slate-100 bg-white p-4 sm:p-5"><div className="mx-auto flex max-w-3xl items-end gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-teal-500 focus-within:ring-2 focus-within:ring-teal-100"><Input.TextArea aria-label="输入问题" value={input} disabled={loading} maxLength={6000} onChange={event => setInput(event.target.value)} onPressEnter={event => { if (!event.shiftKey) { event.preventDefault(); send(); } }} autoSize={{ minRows: 1, maxRows: 5 }} bordered={false} placeholder={mode === "answer" ? "继续追问，或输入新的题号与知识点…" : "描述想练习的知识点和难度…"} />{loading ? <Button danger shape="circle" aria-label="停止生成" icon={<StopOutlined />} onClick={() => requestController.current?.abort()} /> : <Button type="primary" shape="circle" aria-label="发送问题" icon={<SendOutlined />} disabled={!input.trim()} onClick={() => send()} />}</div><p className="mt-2 text-center text-sm text-slate-500">会话自动保存 · Enter 发送 · Shift + Enter 换行</p></footer>
    </section>
    <Drawer open={!!selected} onClose={() => setSelected(null)} width="min(680px, 100vw)" title={selected ? `${selected.ID} · ${selected.qtype}` : "题目详情"}>{selected && <div className="question-markdown space-y-5"><div className="rounded-2xl bg-slate-50 p-5"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{selected.question}</ReactMarkdown></div><div className="flex flex-wrap gap-2">{selected.keypoint?.map(item => <Tag color="cyan" key={item}>{item}</Tag>)}</div>{showAnswer ? <><div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-5 text-emerald-950"><h3 className="mb-3 font-bold">参考答案</h3><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{selected.answer || "暂无"}</ReactMarkdown></div><div className="rounded-2xl border border-sky-100 bg-sky-50 p-5 text-sky-950"><h3 className="mb-3 font-bold">详细解析</h3><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{selected.explanation || "暂无"}</ReactMarkdown></div></> : <Button block size="large" icon={<EyeOutlined />} onClick={() => setShowAnswer(true)}>完成思考后查看答案</Button>}<Button block type="primary" size="large" onClick={() => { setSelected(null); setInput(`请用当前的辅导方式带我完成 ${selected.ID}`); }}>用这道题继续练习</Button></div>}</Drawer>
  </div>;
}
