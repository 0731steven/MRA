import { useEffect, useState } from "react";
import { Alert, Button, Skeleton } from "antd";
import { ArrowRightOutlined, BookOutlined, BulbOutlined, ClockCircleOutlined, ExperimentOutlined, MessageOutlined, ReadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Stats { total: number; qtypes: Record<string, number>; difficulties: Record<string, number>; keypoints: Record<string, number> }
interface LearningSummary { sessions: number; questions_seen: number; assistant_answers: number; attempts: number; attempted_questions: number; correct_questions: number; focus_keypoints: { name: string; count: number }[]; recent_sessions: { id: number; title: string; updated_at: string }[] }

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [learning, setLearning] = useState<LearningSummary | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const teacher = user?.role === "teacher";

  useEffect(() => {
    let active = true;
    setLoadError(false);
    const requests: Promise<unknown>[] = [apiClient.get<Stats>("/api/question-bank/stats").then(response => { if (active) setStats(response.data); })];
    if (!teacher) requests.push(apiClient.get<LearningSummary>("/api/question-bank/learning-summary").then(response => { if (active) setLearning(response.data); }));
    Promise.all(requests).catch(() => { if (active) setLoadError(true); });
    return () => { active = false; };
  }, [teacher, reloadKey]);

  const keypoints = Object.entries(stats?.keypoints || {}).slice(0, 8);
  const accuracy = learning?.attempted_questions ? Math.round((learning.correct_questions / learning.attempted_questions) * 100) : 0;
  const loading = !loadError && (!stats || (!teacher && !learning));

  return (
    <div>
      {loadError && <Alert className="mb-5" type="error" showIcon message="暂时无法载入学习数据" description="请检查网络连接后重试；导航仍可使用，数据将在连接恢复后更新。" action={<Button size="small" onClick={() => setReloadKey(value => value + 1)}>重新加载</Button>} />}

      <section className="relative grid overflow-hidden rounded-2xl bg-slate-950 px-7 py-9 text-white sm:px-9 lg:grid-cols-[1fr_360px] lg:gap-12 lg:px-12 lg:py-12">
        <div className="relative max-w-3xl">
          <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-teal-50/90"><span className="h-2 w-2 rounded-full bg-emerald-300" />你好，{user?.name}</p>
          <h1 className="max-w-2xl text-3xl font-black leading-tight lg:text-[40px]">{teacher ? "把知识点组织成一堂好课" : "从一道题开始，真正理解概率统计"}</h1>
          <p className="mt-4 max-w-xl text-[15px] leading-7 text-teal-50/85">{teacher ? "从专属题库选择例题，快速生成可编辑的课堂教学方案。" : "选择提示、分步引导或完整解析，按照适合你的节奏完成学习闭环。"}</p>
          <div className="mt-7 flex flex-wrap gap-3">
            <button onClick={() => navigate(teacher ? "/teaching" : "/tutor")} className="rounded-xl bg-white px-5 py-3 text-sm font-extrabold text-teal-800 transition hover:bg-teal-50 active:translate-y-px">{teacher ? "创建教学设计" : "开始智能答疑"} <ArrowRightOutlined className="ml-2" /></button>
            <button onClick={() => navigate("/questions")} className="rounded-xl border border-white/30 bg-transparent px-5 py-3 text-sm font-bold text-white transition hover:bg-white/10 active:translate-y-px">浏览课程题库</button>
          </div>
        </div>
        <div className="mt-10 hidden border-l border-slate-700 pl-10 lg:block" aria-label="概率统计公式示例">
          <p className="text-sm font-bold text-teal-300">今日公式</p>
          <div className="mt-5 font-mono text-[28px] font-bold leading-relaxed text-white">P(A|B)</div>
          <div className="font-mono text-xl leading-relaxed text-teal-200">= P(B|A)P(A) / P(B)</div>
          <p className="mt-5 text-sm leading-6 text-slate-300">贝叶斯公式把新的观测证据转化为对事件概率的更新。</p>
          <button onClick={() => navigate("/questions?keypoint=贝叶斯公式")} className="mt-5 text-sm font-bold text-teal-300 hover:text-teal-200">查看相关题目 <ArrowRightOutlined className="ml-1" /></button>
        </div>
      </section>

      <section aria-label="学习概览" className="mt-6 grid overflow-hidden rounded-2xl border border-slate-200 bg-white md:grid-cols-3 md:divide-x md:divide-slate-200">
        {loading ? <div className="col-span-3 grid gap-5 p-6 md:grid-cols-3"><Skeleton active paragraph={{ rows: 2 }} /><Skeleton active paragraph={{ rows: 2 }} /><Skeleton active paragraph={{ rows: 2 }} /></div> : teacher ? <><Stat icon={<BookOutlined />} label="题库总量" value={stats?.total ?? "—"} note="覆盖概率论与数理统计" /><Stat icon={<BulbOutlined />} label="知识点" value={stats ? Object.keys(stats.keypoints).length : "—"} note="支持按考点精准检索" /><Stat icon={<ReadOutlined />} label="题型" value={stats ? Object.keys(stats.qtypes).length : "—"} note={stats ? Object.keys(stats.qtypes).slice(0, 3).join(" · ") : "等待数据恢复"} /></> : <><Stat icon={<MessageOutlined />} label="学习会话" value={learning?.sessions ?? "—"} note="累计保留的答疑会话" /><Stat icon={<BookOutlined />} label="已作答题目" value={learning?.attempted_questions ?? "—"} note={`其中 ${learning?.correct_questions ?? 0} 题已正确完成`} /><Stat icon={<BulbOutlined />} label="当前正确率" value={learning ? `${accuracy}%` : "—"} note={learning?.attempted_questions ? `基于 ${learning.attempted_questions} 道已作答题目` : "完成作答后开始统计"} /></>}
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-[1.25fr_.75fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 lg:p-7">
          <div className="mb-4 flex items-center justify-between gap-4"><div><h2 className="text-lg font-extrabold text-slate-900">{teacher ? "热门知识点" : "我的学习焦点"}</h2><p className="mt-1 text-sm text-slate-500">{teacher ? "选择知识点查看相关题目" : "根据近期答疑引用自动归纳"}</p></div><Button type="link" onClick={() => navigate("/questions")}>全部题目</Button></div>
          {!teacher && learning?.focus_keypoints.length === 0 ? <div className="flex min-h-52 flex-col items-center justify-center border-t border-slate-100 text-center"><BulbOutlined className="text-2xl text-slate-400" /><p className="mt-3 text-sm font-bold text-slate-700">完成第一次答疑后生成学习焦点</p><Button className="mt-2" type="link" onClick={() => navigate("/tutor")}>现在开始</Button></div> : <div className="divide-y divide-slate-100 border-t border-slate-100">
            {(teacher ? keypoints.map(([name, count]) => ({ name, count })) : learning?.focus_keypoints || []).map((item, index) => <button key={item.name} onClick={() => navigate(`/questions?keypoint=${encodeURIComponent(item.name)}`)} className="group flex w-full items-center gap-3 px-1 py-3.5 text-left transition hover:bg-teal-50/70"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-sm font-black text-teal-800">{String(index + 1).padStart(2, "0")}</span><span className="min-w-0 flex-1 truncate text-sm font-bold text-slate-700 group-hover:text-teal-900">{item.name}</span><span className="text-sm text-slate-500">{item.count} 次</span></button>)}
          </div>}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 lg:p-7">
          <h2 className="text-lg font-extrabold text-slate-900">快速开始</h2>
          <div className="mt-4 divide-y divide-slate-100 border-t border-slate-100">
            <Quick icon={<MessageOutlined />} title="按题号问解析" desc="例如：请讲解 P000001" onClick={() => navigate("/tutor?prompt=请讲解 P000001")} />
            <Quick icon={<BulbOutlined />} title="推荐练习题" desc="按知识点和难度智能推荐" onClick={() => navigate("/tutor?mode=recommend")} />
            <Quick icon={<ExperimentOutlined />} title="参数化实验" desc="调节参数并运行概率统计模拟" onClick={() => navigate("/experiments")} />
            {teacher && <Quick icon={<ReadOutlined />} title="设计一节课" desc="从题库选例题生成课堂方案" onClick={() => navigate("/teaching")} />}
            {!teacher && learning?.recent_sessions.slice(0, 1).map(item => <Quick key={item.id} icon={<ClockCircleOutlined />} title="继续最近学习" desc={item.title} onClick={() => navigate("/tutor")} />)}
          </div>
        </div>
      </section>
    </div>
  );
}

function Stat({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: number | string; note: string }) {
  return <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-6 last:border-b-0 md:border-b-0"><div><p className="text-sm font-semibold text-slate-500">{label}</p><p className="mt-1.5 text-3xl font-black tracking-tight text-slate-900">{value}</p><p className="mt-1.5 text-sm text-slate-500">{note}</p></div><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-lg text-teal-800">{icon}</span></div>;
}

function Quick({ icon, title, desc, onClick }: { icon: React.ReactNode; title: string; desc: string; onClick: () => void }) {
  return <button onClick={onClick} className="group flex w-full items-center gap-3 py-3.5 text-left transition hover:bg-teal-50/70"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-800">{icon}</span><span className="min-w-0 flex-1"><span className="block text-sm font-bold text-slate-800 group-hover:text-teal-950">{title}</span><span className="mt-0.5 block truncate text-sm text-slate-500 group-hover:text-teal-800">{desc}</span></span><ArrowRightOutlined className="text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-teal-700" /></button>;
}
