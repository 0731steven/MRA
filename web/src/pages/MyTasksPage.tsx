import { useEffect, useState } from "react";
import { Alert, Button, Empty, Form, Input, Progress, Skeleton, Tag, message } from "antd";
import { ArrowRightOutlined, CheckCircleOutlined, CheckSquareOutlined, LinkOutlined, ReloadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Classroom { id: number; name: string; course_name: string; members: number; assignments: number }
interface Task { id: number; classroom_id: number; classroom_name: string; title: string; description?: string; kind: "diagnostic" | "intervention" | "retest"; topic: string; question_ids: string[]; attempted_questions: number; my_status: "assigned" | "completed"; group_label?: string; due_at?: string }

const kindMeta = {
  diagnostic: { label: "课堂诊断", color: "blue" },
  intervention: { label: "分组干预", color: "orange" },
  retest: { label: "迁移验证", color: "green" },
};

export default function MyTasksPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const student = user?.role === "student";
  const [tasks, setTasks] = useState<Task[]>([]);
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [joining, setJoining] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [taskResponse, classResponse] = await Promise.all([
        apiClient.get<Task[]>("/api/assignments/mine"),
        apiClient.get<Classroom[]>("/api/classrooms"),
      ]);
      setTasks(taskResponse.data);
      setClassrooms(classResponse.data);
      setError(false);
    } catch { setError(true); } finally { setLoading(false); }
  }

  useEffect(() => { if (student) void load(); }, [student]);

  if (!student) return <Alert type="warning" showIcon message="“我的任务”仅供学生使用" description="教师可以在“班级认知雷达”中发布任务并查看完成情况。" />;

  async function join(values: { join_code: string }) {
    setJoining(true);
    try {
      const response = await apiClient.post<{ name: string }>("/api/classrooms/join", { join_code: values.join_code.trim().toUpperCase() });
      message.success(`已加入“${response.data.name}”`);
      await load();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "加入班级失败，请确认班级码后重试");
    } finally { setJoining(false); }
  }

  const pending = tasks.filter(item => item.my_status !== "completed");
  const completed = tasks.filter(item => item.my_status === "completed");
  const joinForm = <Form layout="inline" onFinish={join} className="gap-y-3"><Form.Item name="join_code" rules={[{ required: true, message: "请输入班级码" }, { len: 7, message: "班级码为 7 位" }]}><Input className="!w-48 !font-mono !font-bold !tracking-wider" maxLength={7} placeholder="输入班级码" prefix={<LinkOutlined />} /></Form.Item><Form.Item><Button type="primary" htmlType="submit" loading={joining}>加入班级</Button></Form.Item></Form>;

  return <div className="mx-auto max-w-6xl">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-bold text-slate-950">我的任务</h1><p className="mt-1 max-w-3xl text-base leading-7 text-slate-600">完成教师发布的诊断与干预；最后一道题会检查你是否能在无提示下独立迁移。</p></div><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新任务</Button></div>

    {classrooms.length === 0 ? <section className="mt-6 grid gap-5 border border-slate-200 bg-white px-5 py-5 md:grid-cols-[1fr_auto] md:items-center" aria-labelledby="join-heading"><div><h2 id="join-heading" className="text-lg font-bold text-slate-900">加入课程班级</h2><p className="mt-1 text-sm text-slate-600">向任课教师获取 7 位班级码。加入后，教师发布的任务会出现在本页。</p></div>{joinForm}</section> : <details className="mt-5 border-y border-slate-200 bg-white"><summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-2 px-5 py-3 text-sm font-semibold text-slate-700"><span>已加入 {classrooms.length} 个班级</span>{classrooms.map(item => <Tag key={item.id} color="cyan">{item.name}</Tag>)}<span className="ml-auto text-teal-700">加入其他班级</span></summary><div className="border-t border-slate-100 px-5 py-4">{joinForm}</div></details>}
    {error && <Alert className="mt-5" type="error" showIcon message="任务暂时无法载入" description="请检查连接后重试；已经提交的作答不会丢失。" action={<Button size="small" onClick={load}>重新加载</Button>} />}

    {loading ? <div className="mt-6 space-y-4"><Skeleton active /><Skeleton active /></div> : <>
      <section className="mt-6" aria-labelledby="pending-heading"><div className="mb-3 flex items-center justify-between"><h2 id="pending-heading" className="text-lg font-bold text-slate-900">待完成</h2><span className="text-sm font-semibold text-slate-600">{pending.length} 项</span></div>{pending.length === 0 ? <div className="border border-slate-200 bg-white py-10"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={classrooms.length ? "当前没有待完成任务" : "加入班级后在这里接收任务"} /></div> : <div className="divide-y divide-slate-100 border border-slate-200 bg-white">{pending.map(task => <TaskRow key={task.id} task={task} onOpen={questionId => navigate(`/questions?query=${questionId}&task=1&assignment=${task.id}`)} />)}</div>}</section>
      {completed.length > 0 && <details className="mt-8"><summary className="flex min-h-12 cursor-pointer list-none items-center justify-between border-b border-slate-200 py-3"><span className="text-lg font-bold text-slate-900">已完成</span><span className="text-sm font-semibold text-slate-600">{completed.length} 项 · 展开历史</span></summary><div className="divide-y divide-slate-100 border-x border-b border-slate-200 bg-white">{completed.map(task => <TaskRow key={task.id} task={task} onOpen={questionId => navigate(`/questions?query=${questionId}&task=1&assignment=${task.id}`)} />)}</div></details>}
    </>}
  </div>;
}

function TaskRow({ task, onOpen }: { task: Task; onOpen: (questionId: string) => void }) {
  const meta = kindMeta[task.kind];
  const total = task.question_ids.length;
  const done = Math.min(task.attempted_questions, total);
  const percent = total ? Math.round(done / total * 100) : 0;
  const nextQuestion = task.question_ids[Math.min(done, Math.max(total - 1, 0))];
  return <article className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_180px_auto] md:items-center">
    <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Tag color={meta.color}>{meta.label}</Tag>{task.group_label && <Tag>{task.group_label}</Tag>}{task.my_status === "completed" && <span className="text-sm font-semibold text-emerald-700"><CheckCircleOutlined className="mr-1" />已完成</span>}{task.due_at && task.my_status !== "completed" && <Tag color={new Date(task.due_at).getTime() < Date.now() ? "red" : "gold"}>{new Date(task.due_at).getTime() < Date.now() ? "已截止" : `截止 ${new Date(task.due_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`}</Tag>}</div><h3 className="mt-2 font-semibold text-slate-950">{task.title}</h3><p className="mt-1 text-sm text-slate-600">{task.classroom_name} · {task.topic} · {total} 道题</p>{task.description && <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{task.description}</p>}</div>
    <div><div className="mb-1.5 flex justify-between text-sm text-slate-500"><span>完成进度</span><span className="font-semibold tabular-nums">{done}/{total}</span></div><Progress percent={percent} size="small" showInfo={false} strokeColor={task.my_status === "completed" ? "#16a34a" : "#0f766e"} /></div>
    <Button type={task.my_status === "completed" ? "default" : "primary"} icon={task.my_status === "completed" ? <CheckSquareOutlined /> : <ArrowRightOutlined />} disabled={!nextQuestion} onClick={() => nextQuestion && onOpen(nextQuestion)}>{task.my_status === "completed" ? "查看任务" : done ? "继续完成" : "开始任务"}</Button>
  </article>;
}
