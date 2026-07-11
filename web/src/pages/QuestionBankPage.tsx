import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Drawer, Empty, Input, Pagination, Radio, Segmented, Select, Skeleton, Tag, Upload, message } from "antd";
import type { UploadFile } from "antd";
import { BulbOutlined, CameraOutlined, EyeOutlined, FormOutlined, SearchOutlined, SendOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Question { ID: string; qtype: string; question: string; choices: string[] | null; keypoint: string[]; hard_level: string; answer?: string; explanation?: string }
interface Stats { total: number; qtypes: Record<string, number>; difficulties: Record<string, number>; keypoints: Record<string, number> }
interface Diagnostic { verdict: "correct" | "partial" | "incorrect" | "needs_review"; feedback: string; error_type?: string; attempt_no: number }

const formulaKeys = [
  ["分式", "\\frac{}{}"], ["根号", "\\sqrt{}"], ["上标", "^{}"], ["下标", "_{}"],
  ["求和", "\\sum_{}^{}"], ["积分", "\\int_{}^{}"], ["条件概率", "P(A\\mid B)"],
  ["期望", "E(X)"], ["方差", "D(X)"], ["组合数", "\\binom{}{}"], ["μ", "\\mu"], ["σ", "\\sigma"],
];

export default function QuestionBankPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("query") || "";
  const qtype = params.get("qtype") || "";
  const difficulty = params.get("difficulty") || "";
  const keypoint = params.get("keypoint") || "";
  const page = Number(params.get("page") || 1);
  const [searchText, setSearchText] = useState(query);
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Question[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Question | null>(null);
  const [inputMode, setInputMode] = useState("formula");
  const [answer, setAnswer] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [file, setFile] = useState<UploadFile | null>(null);
  const [imageDataUrl, setImageDataUrl] = useState("");
  const [diagnostic, setDiagnostic] = useState<Diagnostic | null>(null);
  const [hint, setHint] = useState("");
  const [hintCount, setHintCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [showAnswer, setShowAnswer] = useState(false);
  useEffect(() => { apiClient.get<Stats>("/api/question-bank/stats").then(r => setStats(r.data)); }, []);
  useEffect(() => { setSearchText(query); }, [query]);
  useEffect(() => { setLoading(true); apiClient.get("/api/question-bank/questions", { params: { page, page_size: 12, query, qtype, difficulty, keypoint } }).then(r => { setItems(r.data.items); setTotal(r.data.total); }).finally(() => setLoading(false)); }, [page, query, qtype, difficulty, keypoint]);
  const update = (key: string, value: string | number) => { const next = new URLSearchParams(params); value ? next.set(key, String(value)) : next.delete(key); if (key !== "page") next.delete("page"); setParams(next); };
  const clearFilters = () => { setSearchText(""); setParams(new URLSearchParams()); };
  async function open(id: string) { const r = await apiClient.get<Question>(`/api/question-bank/questions/${id}`); setSelected(r.data); setAnswer(""); setReasoning(""); setFile(null); setImageDataUrl(""); setDiagnostic(null); setHint(""); setHintCount(0); setShowAnswer(false); }
  async function requestHint() { if (!selected) return; const r = await apiClient.post(`/api/question-bank/questions/${selected.ID}/hint`, { answer, reasoning }); setHint(r.data.hint); setHintCount(value => value + 1); }
  async function submitAttempt() { if (!selected) return; setSubmitting(true); try { const r = await apiClient.post<Diagnostic>(`/api/question-bank/questions/${selected.ID}/attempts`, { answer, reasoning, input_mode: inputMode, image_name: file?.name, image_data_url: imageDataUrl, hint_count: hintCount }); setDiagnostic(r.data); message.success("作答已保存"); } catch (error: unknown) { const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail; message.error(detail || "提交失败"); } finally { setSubmitting(false); } }
  return <div>
    <div className="mb-6"><h1 className="text-2xl font-black text-slate-900">概率统计题库</h1><p className="mt-1 text-sm text-slate-400">共收录 {stats?.total ?? 1007} 道题，支持题号、题干和知识点检索</p></div>
    <div className="mb-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="grid gap-3 lg:grid-cols-[1fr_180px_150px_210px]"><Input.Search allowClear size="large" value={searchText} enterButton={<SearchOutlined />} placeholder="搜索题号、题干或知识点" onChange={event => setSearchText(event.target.value)} onSearch={value => update("query", value.trim())} /><Select allowClear size="large" value={qtype || undefined} placeholder="全部题型" options={Object.keys(stats?.qtypes || {}).map(v => ({ label: v, value: v }))} onChange={v => update("qtype", v || "")} /><Select allowClear size="large" value={difficulty || undefined} placeholder="全部难度" options={Object.keys(stats?.difficulties || {}).map(v => ({ label: v, value: v }))} onChange={v => update("difficulty", v || "")} /><Select showSearch allowClear size="large" value={keypoint || undefined} placeholder="全部知识点" options={Object.keys(stats?.keypoints || {}).map(v => ({ label: v, value: v }))} onChange={v => update("keypoint", v || "")} /></div>
      {(query || qtype || difficulty || keypoint) && <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4"><span className="mr-1 text-xs font-bold text-slate-400">当前筛选</span>{query && <Tag color="cyan">关键词：{query}</Tag>}{qtype && <Tag>{qtype}</Tag>}{difficulty && <Tag color="orange">{difficulty}</Tag>}{keypoint && <Tag color="geekblue">{keypoint}</Tag>}<Button type="link" size="small" onClick={clearFilters}>清除全部</Button><span className="ml-auto text-xs text-slate-400">找到 {total} 道题</span></div>}
    </div>
    {loading ? <div className="grid gap-4 md:grid-cols-2"><Skeleton active /><Skeleton active /></div> : items.length === 0 ? <Empty description="没有找到匹配的题目" /> : <div className="grid gap-4 md:grid-cols-2">{items.map(q => <article key={q.ID} className="flex min-h-52 flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"><div className="mb-4 flex items-center gap-2"><span className="rounded-lg bg-teal-700 px-2.5 py-1 text-xs font-extrabold text-white">{q.ID}</span><Tag>{q.qtype}</Tag><Tag color={q.hard_level === "难" ? "red" : q.hard_level === "中" ? "orange" : "green"}>{q.hard_level}</Tag></div><div className="line-clamp-4 flex-1 text-[15px] leading-7 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{q.question}</ReactMarkdown></div><div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4"><div className="flex max-w-[72%] gap-1 overflow-hidden">{q.keypoint?.slice(0, 2).map(k => <span key={k} className="whitespace-nowrap rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-500">{k}</span>)}</div><Button type="text" icon={<EyeOutlined />} onClick={() => open(q.ID)}>查看</Button></div></article>)}</div>}
    {total > 12 && <div className="mt-8 flex justify-center"><Pagination current={page} pageSize={12} total={total} showSizeChanger={false} onChange={p => update("page", p)} /></div>}
    <Drawer open={!!selected} onClose={() => setSelected(null)} width={720} title={selected ? `${selected.ID} · ${selected.qtype} · ${selected.hard_level}` : "题目详情"}>{selected && <div className="question-markdown space-y-5"><Block title="题目" text={selected.question} /><div className="flex flex-wrap gap-2">{selected.keypoint?.map(k => <Tag color="cyan" key={k}>{k}</Tag>)}</div><section className="rounded-2xl border border-slate-200 p-5"><div className="mb-4 flex items-center justify-between gap-3"><div><h3 className="font-extrabold text-slate-800">提交你的作答</h3><p className="mt-1 text-xs text-slate-400">不要求完整输入所有推导，可填写答案、描述思路或附上手写过程</p></div><FormOutlined className="text-xl text-teal-700" /></div><Segmented block value={inputMode} onChange={value => setInputMode(String(value))} options={[{ label: "公式 / 答案", value: "formula" }, { label: "描述思路", value: "reasoning" }, { label: "手写图片", value: "image" }]} />
      <div className="mt-5">{selected.qtype === "多选题" && selected.choices ? <Checkbox.Group className="!grid !gap-3" options={selected.choices.map(item => ({ label: <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{item}</ReactMarkdown>, value: item.match(/^\(\d+\)/)?.[0] || item }))} onChange={values => setAnswer(values.join("，"))} /> : selected.qtype === "判断题" ? <Radio.Group value={answer} onChange={event => setAnswer(event.target.value)} options={[{ label: "正确", value: "正确" }, { label: "错误", value: "错误" }]} /> : inputMode === "formula" ? <><div className="mb-3 flex flex-wrap gap-2">{formulaKeys.map(([label, token]) => <Button key={label} size="small" onClick={() => setAnswer(value => value + token)}>{label}</Button>)}</div><Input.TextArea value={answer} onChange={event => setAnswer(event.target.value)} rows={3} placeholder="输入最终答案或公式，例如：\\frac{1}{2}" />{answer && <div className="mt-3 rounded-xl bg-slate-50 p-4 text-center"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{`$$${answer}$$`}</ReactMarkdown></div>}</> : inputMode === "reasoning" ? <Input.TextArea value={reasoning} onChange={event => setReasoning(event.target.value)} rows={6} placeholder="例如：我先用全概率公式求分母，再用贝叶斯公式计算……" /> : <div><Upload.Dragger accept="image/*" maxCount={1} beforeUpload={upload => { if (upload.size > 2_000_000) { message.error("图片请控制在 2MB 以内"); return Upload.LIST_IGNORE; } setFile(upload); const reader = new FileReader(); reader.onload = () => setImageDataUrl(String(reader.result || "")); reader.readAsDataURL(upload); return false; }} onRemove={() => { setFile(null); setImageDataUrl(""); }} fileList={file ? [file] : []}><p className="text-2xl text-teal-700"><CameraOutlined /></p><p className="mt-2 text-sm font-bold text-slate-700">上传手写过程照片</p><p className="mt-1 text-xs text-slate-400">图片会随作答保存；请补充关键公式或结论，避免手写识别歧义</p></Upload.Dragger><Input.TextArea className="mt-3" value={reasoning} onChange={event => setReasoning(event.target.value)} rows={3} placeholder="补充图片中的关键步骤或结论（推荐）" /></div>}</div>
      {inputMode !== "reasoning" && selected.qtype !== "判断题" && selected.qtype !== "多选题" && <Input.TextArea className="mt-3" value={reasoning} onChange={event => setReasoning(event.target.value)} rows={3} placeholder="可选：用自然语言描述你的解题思路" />}
      {hint && <Alert className="mt-4" type="info" showIcon message="启发提示" description={hint} />}{diagnostic && <Alert className="mt-4" type={diagnostic.verdict === "correct" ? "success" : diagnostic.verdict === "incorrect" ? "error" : "warning"} showIcon message={diagnostic.verdict === "correct" ? `第 ${diagnostic.attempt_no} 次作答正确` : `第 ${diagnostic.attempt_no} 次作答诊断`} description={<div>{diagnostic.feedback}{diagnostic.error_type && <Tag className="ml-2" color="orange">{diagnostic.error_type}</Tag>}</div>} />}
      <div className="mt-4 flex gap-3"><Button icon={<BulbOutlined />} onClick={requestHint}>给我一个提示{hintCount ? ` (${hintCount})` : ""}</Button><Button type="primary" icon={<SendOutlined />} loading={submitting} onClick={submitAttempt}>提交检查</Button></div></section>
      {showAnswer ? <><Block title="参考答案" text={selected.answer || "暂无"} tone="green" /><Block title="详细解析" text={selected.explanation || "暂无"} tone="blue" /></> : <Button block size="large" icon={<EyeOutlined />} onClick={() => setShowAnswer(true)}>完成作答后查看答案与解析</Button>}</div>}</Drawer>
  </div>;
}
function Block({ title, text, tone = "slate" }: { title: string; text: string; tone?: "slate" | "green" | "blue" }) { const cls = tone === "green" ? "bg-emerald-50 border-emerald-100" : tone === "blue" ? "bg-sky-50 border-sky-100" : "bg-slate-50 border-slate-100"; return <section className={`rounded-2xl border p-5 ${cls}`}><h3 className="mb-3 text-sm font-extrabold text-slate-800">{title}</h3><div className="text-[15px] leading-8 text-slate-700"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{text}</ReactMarkdown></div></section> }
