import { useEffect, useState } from "react";
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
  const teacher = user?.role === "teacher";
  useEffect(() => {
    apiClient.get<Stats>("/api/question-bank/stats").then(r => setStats(r.data));
    if (!teacher) apiClient.get<LearningSummary>("/api/question-bank/learning-summary").then(r => setLearning(r.data));
  }, [teacher]);
  const keypoints = Object.entries(stats?.keypoints || {}).slice(0, 8);
  const accuracy = learning?.attempted_questions ? Math.round((learning.correct_questions / learning.attempted_questions) * 100) : 0;
  return (
    <div>
      <section className="relative overflow-hidden rounded-[30px] bg-gradient-to-br from-[#073f3c] via-[#0b615b] to-[#0f766e] px-7 py-9 text-white shadow-[0_20px_55px_rgba(15,118,110,.16)] sm:px-9 lg:px-12 lg:py-11">
        <div className="absolute -right-16 -top-24 h-80 w-80 rounded-full border-[50px] border-white/5" />
        <div className="absolute bottom-0 right-[18%] h-24 w-24 translate-y-12 rounded-full bg-emerald-300/10 blur-xl" />
        <div className="relative max-w-3xl">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-bold text-teal-50"><span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />你好，{user?.name}</div>
          <h1 className="max-w-2xl text-3xl font-black leading-tight tracking-tight lg:text-[42px]">{teacher ? "把知识点组织成一堂好课" : "从一道题开始，真正理解概率统计"}</h1>
          <p className="mt-4 max-w-xl text-sm leading-7 text-teal-50/70">{teacher ? "从专属题库选择例题，快速生成可编辑的课堂教学方案。" : "选择提示、分步引导或完整解析，按照适合你的节奏完成学习闭环。"}</p>
          <div className="mt-7 flex flex-wrap gap-3">
            <button onClick={() => navigate(teacher ? "/teaching" : "/tutor")} className="rounded-xl bg-white px-5 py-3 text-sm font-extrabold text-teal-800 shadow-lg shadow-slate-950/10">{teacher ? "创建教学设计" : "开始智能答疑"} <ArrowRightOutlined className="ml-2" /></button>
            <button onClick={() => navigate("/questions")} className="rounded-xl border border-white/20 bg-white/10 px-5 py-3 text-sm font-bold text-white transition hover:bg-white/15">浏览课程题库</button>
          </div>
        </div>
        <div className="absolute bottom-8 right-9 hidden w-64 rotate-[-2deg] rounded-2xl border border-white/10 bg-white/10 p-5 backdrop-blur-md xl:block">
          <div className="flex items-center justify-between text-[10px] font-bold tracking-widest text-teal-100/70"><span>今日学习路径</span><span>3 STEPS</span></div>
          <div className="mt-4 space-y-3 text-xs font-semibold"><div className="flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-teal-800">1</span>选择知识点或题目</div><div className="flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/15">2</span>尝试作答并获取提示</div><div className="flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/15">3</span>复盘解析与实验验证</div></div>
        </div>
      </section>
      <section className="mt-7 grid gap-5 md:grid-cols-3">
        {teacher ? <><Stat icon={<BookOutlined />} label="题库总量" value={stats?.total ?? "—"} note="覆盖概率论与数理统计" /><Stat icon={<BulbOutlined />} label="知识点" value={stats ? Object.keys(stats.keypoints).length : "—"} note="支持按考点精准检索" /><Stat icon={<ReadOutlined />} label="题型" value={stats ? Object.keys(stats.qtypes).length : "—"} note={Object.keys(stats?.qtypes || {}).slice(0, 3).join(" · ")} /></> : <><Stat icon={<MessageOutlined />} label="学习会话" value={learning?.sessions ?? "—"} note="累计保留的答疑会话" /><Stat icon={<BookOutlined />} label="已作答题目" value={learning?.attempted_questions ?? "—"} note={`其中 ${learning?.correct_questions ?? 0} 题已正确完成`} /><Stat icon={<BulbOutlined />} label="当前正确率" value={learning ? `${accuracy}%` : "—"} note={learning?.attempted_questions ? `基于 ${learning.attempted_questions} 道已作答题目` : "完成作答后开始统计"} /></>}
      </section>
      <section className="mt-7 grid gap-6 lg:grid-cols-[1.25fr_.75fr]">
        <div className="rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
          <div className="mb-5 flex items-center justify-between"><div><h2 className="text-lg font-extrabold text-slate-900">{teacher ? "热门知识点" : "我的学习焦点"}</h2><p className="mt-1 text-xs text-slate-400">{teacher ? "点击即可查看相关题目" : "根据近期答疑引用自动归纳"}</p></div><button onClick={() => navigate("/questions")} className="text-sm font-bold text-teal-700">全部题目</button></div>
          {!teacher && learning?.focus_keypoints.length === 0 ? <div className="flex min-h-52 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 text-center"><BulbOutlined className="text-2xl text-slate-300" /><p className="mt-3 text-sm font-bold text-slate-600">完成第一次答疑后生成学习焦点</p><button onClick={() => navigate("/tutor")} className="mt-3 text-sm font-bold text-teal-700">现在开始</button></div> : <div className="grid gap-3 sm:grid-cols-2">
            {(teacher ? keypoints.map(([name, count]) => ({ name, count })) : learning?.focus_keypoints || []).map((item, i) => <button key={item.name} onClick={() => navigate(`/questions?keypoint=${encodeURIComponent(item.name)}`)} className="group flex items-center gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-4 text-left hover:border-teal-200 hover:bg-teal-50"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-xs font-black text-teal-700 shadow-sm">{String(i + 1).padStart(2, "0")}</span><span className="flex-1 text-sm font-bold text-slate-700 group-hover:text-teal-800">{item.name}</span><span className="text-xs text-slate-400">{item.count} 次</span></button>)}
          </div>}
        </div>
        <div className="rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
          <h2 className="text-lg font-extrabold text-slate-900">快速开始</h2>
          <div className="mt-5 space-y-3">
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

function Stat({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: number | string; note: string }) { return <div className="group rounded-3xl border border-slate-200/90 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"><div className="flex items-start justify-between"><div><p className="text-sm font-semibold text-slate-400">{label}</p><p className="mt-2 text-3xl font-black tracking-tight text-slate-900">{value}</p><p className="mt-2 text-xs text-slate-400">{note}</p></div><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-teal-50 text-lg text-teal-700 transition group-hover:bg-teal-100">{icon}</span></div></div> }
function Quick({ icon, title, desc, onClick }: { icon: React.ReactNode; title: string; desc: string; onClick: () => void }) { return <button onClick={onClick} className="group flex w-full items-center gap-4 rounded-2xl border border-slate-100 p-4 text-left transition hover:border-teal-200 hover:bg-teal-50/60"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-700 transition group-hover:bg-white">{icon}</span><span className="flex-1"><span className="block text-sm font-bold text-slate-800">{title}</span><span className="mt-1 block text-xs text-slate-400">{desc}</span></span><ArrowRightOutlined className="text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-teal-700" /></button> }
