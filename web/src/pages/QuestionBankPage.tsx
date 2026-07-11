import { useEffect, useState } from "react";
import { Button, Drawer, Empty, Input, Pagination, Select, Skeleton, Tag } from "antd";
import { EyeOutlined, SearchOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Question { ID: string; qtype: string; question: string; choices: unknown; keypoint: string[]; hard_level: string; answer?: string; explanation?: string }
interface Stats { total: number; qtypes: Record<string, number>; difficulties: Record<string, number>; keypoints: Record<string, number> }

export default function QuestionBankPage() {
  const [params, setParams] = useSearchParams();
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Question[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Question | null>(null);
  const page = Number(params.get("page") || 1);
  const query = params.get("query") || "", qtype = params.get("qtype") || "", difficulty = params.get("difficulty") || "", keypoint = params.get("keypoint") || "";
  useEffect(() => { apiClient.get<Stats>("/api/question-bank/stats").then(r => setStats(r.data)); }, []);
  useEffect(() => { setLoading(true); apiClient.get("/api/question-bank/questions", { params: { page, page_size: 12, query, qtype, difficulty, keypoint } }).then(r => { setItems(r.data.items); setTotal(r.data.total); }).finally(() => setLoading(false)); }, [page, query, qtype, difficulty, keypoint]);
  const update = (key: string, value: string | number) => { const next = new URLSearchParams(params); value ? next.set(key, String(value)) : next.delete(key); if (key !== "page") next.delete("page"); setParams(next); };
  async function open(id: string) { const r = await apiClient.get<Question>(`/api/question-bank/questions/${id}`); setSelected(r.data); }
  return <div>
    <div className="mb-6"><h1 className="text-2xl font-black text-slate-900">概率统计题库</h1><p className="mt-1 text-sm text-slate-400">共收录 {stats?.total ?? 1007} 道题，支持题号、题干和知识点检索</p></div>
    <div className="mb-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><div className="grid gap-3 lg:grid-cols-[1fr_180px_150px_210px]"><Input allowClear size="large" prefix={<SearchOutlined />} defaultValue={query} placeholder="搜索题号、题干或知识点" onPressEnter={e => update("query", e.currentTarget.value)} onClear={() => update("query", "")} /><Select allowClear size="large" value={qtype || undefined} placeholder="全部题型" options={Object.keys(stats?.qtypes || {}).map(v => ({ label: v, value: v }))} onChange={v => update("qtype", v || "")} /><Select allowClear size="large" value={difficulty || undefined} placeholder="全部难度" options={Object.keys(stats?.difficulties || {}).map(v => ({ label: v, value: v }))} onChange={v => update("difficulty", v || "")} /><Select showSearch allowClear size="large" value={keypoint || undefined} placeholder="全部知识点" options={Object.keys(stats?.keypoints || {}).map(v => ({ label: v, value: v }))} onChange={v => update("keypoint", v || "")} /></div></div>
    {loading ? <div className="grid gap-4 md:grid-cols-2"><Skeleton active /><Skeleton active /></div> : items.length === 0 ? <Empty description="没有找到匹配的题目" /> : <div className="grid gap-4 md:grid-cols-2">{items.map(q => <article key={q.ID} className="flex min-h-52 flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"><div className="mb-4 flex items-center gap-2"><span className="rounded-lg bg-teal-700 px-2.5 py-1 text-xs font-extrabold text-white">{q.ID}</span><Tag>{q.qtype}</Tag><Tag color={q.hard_level === "难" ? "red" : q.hard_level === "中" ? "orange" : "green"}>{q.hard_level}</Tag></div><div className="line-clamp-4 flex-1 text-[15px] leading-7 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{q.question}</ReactMarkdown></div><div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4"><div className="flex max-w-[72%] gap-1 overflow-hidden">{q.keypoint?.slice(0, 2).map(k => <span key={k} className="whitespace-nowrap rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-500">{k}</span>)}</div><Button type="text" icon={<EyeOutlined />} onClick={() => open(q.ID)}>查看</Button></div></article>)}</div>}
    {total > 12 && <div className="mt-8 flex justify-center"><Pagination current={page} pageSize={12} total={total} showSizeChanger={false} onChange={p => update("page", p)} /></div>}
    <Drawer open={!!selected} onClose={() => setSelected(null)} width={680} title={selected ? `${selected.ID} · ${selected.qtype}` : "题目详情"}>{selected && <div className="question-markdown space-y-6"><Block title="题目" text={selected.question} /><div className="flex gap-2">{selected.keypoint?.map(k => <Tag color="cyan" key={k}>{k}</Tag>)}</div><Block title="参考答案" text={selected.answer || "暂无"} tone="green" /><Block title="详细解析" text={selected.explanation || "暂无"} tone="blue" /></div>}</Drawer>
  </div>;
}
function Block({ title, text, tone = "slate" }: { title: string; text: string; tone?: "slate" | "green" | "blue" }) { const cls = tone === "green" ? "bg-emerald-50 border-emerald-100" : tone === "blue" ? "bg-sky-50 border-sky-100" : "bg-slate-50 border-slate-100"; return <section className={`rounded-2xl border p-5 ${cls}`}><h3 className="mb-3 text-sm font-extrabold text-slate-800">{title}</h3><div className="text-[15px] leading-8 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{text}</ReactMarkdown></div></section> }
