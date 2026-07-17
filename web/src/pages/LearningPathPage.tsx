import { useEffect, useState } from "react";
import { Alert, Button, Empty, Progress, Skeleton, Tag } from "antd";
import {
  ArrowRightOutlined,
  BookOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/api/client";

interface Mastery {
  id: string;
  name: string;
  score: number;
  confidence: number;
  status: "mastered" | "developing" | "at_risk";
  trend: "up" | "down" | "steady";
  attempts: number;
  questions: number;
  hint_count: number;
  top_error?: string;
}

interface RiskAlert {
  severity: "high" | "medium" | "low";
  keypoint: string;
  title: string;
  message: string;
  recommendation: string;
  evidence: { attempts: number; questions: number; hints: number; top_error?: string };
}

interface PathStep {
  order: number;
  type: "review" | "practice" | "experiment";
  title: string;
  keypoint: string;
  reason: string;
  question_ids: string[];
  difficulty: string[];
  experiment_id?: string;
  completed: boolean;
}

interface LearningProfile {
  summary: {
    overall_mastery: number;
    assessed_keypoints: number;
    strong_keypoints: number;
    risk_keypoints: number;
    next_focus: string;
    evidence_level: "low" | "medium" | "high";
  };
  evidence: { attempts: number; questions: number; keypoints: number };
  mastery: Mastery[];
  alerts: RiskAlert[];
  path: PathStep[];
}

const evidenceLabel = { low: "证据积累中", medium: "中等可信", high: "高可信" };
const statusLabel = { mastered: "已掌握", developing: "发展中", at_risk: "需巩固" };

export default function LearningPathPage() {
  const navigate = useNavigate();
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    apiClient.get<LearningProfile>("/api/question-bank/learning-profile")
      .then(response => { if (active) setProfile(response.data); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reloadKey]);

  if (loading) return <div className="space-y-6"><Skeleton active paragraph={{ rows: 4 }} /><Skeleton active paragraph={{ rows: 8 }} /></div>;
  if (error || !profile) return <Alert type="error" showIcon message="学习路径暂时无法生成" description="你的作答记录没有丢失，请稍后重新计算。" action={<Button icon={<ReloadOutlined />} onClick={() => setReloadKey(value => value + 1)}>重新计算</Button>} />;

  const noEvidence = profile.evidence.questions === 0;
  const visibleMastery = showAll ? profile.mastery : profile.mastery.slice(0, 8);

  return <div className="mx-auto max-w-7xl">
    <header className="overflow-hidden rounded-2xl bg-slate-950 text-white">
      <div className="grid gap-8 px-6 py-8 sm:px-8 lg:grid-cols-[1fr_340px] lg:px-10 lg:py-10">
        <div className="max-w-3xl">
          <div className="mb-3 flex flex-wrap items-center gap-2"><Tag color="cyan" className="!m-0">{evidenceLabel[profile.summary.evidence_level]}</Tag><span className="text-sm text-slate-300">基于 {profile.evidence.questions} 道题、{profile.evidence.attempts} 次作答</span></div>
          <h1 className="text-3xl font-black leading-tight">下一步，先学好“{profile.summary.next_focus}”</h1>
          <p className="mt-3 max-w-2xl text-[15px] leading-7 text-slate-300">路径依据题库知识点、作答结果、错误类型和提示使用情况生成。每完成一组题，掌握度和后续顺序都会更新。</p>
          <Button className="!mt-6" type="primary" size="large" onClick={() => profile.path[0]?.question_ids[0] ? navigate(`/questions?query=${profile.path[0].question_ids[0]}&task=1`) : navigate("/questions")}>
            开始当前任务 <ArrowRightOutlined />
          </Button>
        </div>
        <div className="flex items-center gap-6 border-t border-slate-700 pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <Progress type="circle" percent={profile.summary.overall_mastery} size={116} strokeColor="#2dd4bf" trailColor="#334155" format={value => <span className="font-black text-white">{value}%</span>} />
          <div className="space-y-2 text-sm"><p><span className="font-black text-emerald-300">{profile.summary.strong_keypoints}</span> 个知识点已掌握</p><p><span className="font-black text-amber-300">{profile.summary.risk_keypoints}</span> 个知识点需巩固</p><p className="text-slate-400">已评估 {profile.summary.assessed_keypoints} 个知识点</p></div>
        </div>
      </div>
    </header>

    {noEvidence && <Alert className="mt-6" type="info" showIcon message="先完成第一组基础诊断" description="目前还没有作答证据，系统已从样本空间开始安排基础题。完成后会生成你的第一份掌握度画像。" />}

    <div className="mt-6 grid items-start gap-6 xl:grid-cols-[1.1fr_.9fr]">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-labelledby="path-heading">
        <div className="border-b border-slate-200 px-6 py-5"><h2 id="path-heading" className="text-lg font-extrabold text-slate-900">个性化学习路径</h2><p className="mt-1 text-sm text-slate-600">按顺序完成；前置回补会优先于当前薄弱知识点。</p></div>
        <ol className="divide-y divide-slate-100">
          {profile.path.map(step => <li key={`${step.order}-${step.title}`} className="grid gap-4 px-6 py-5 sm:grid-cols-[46px_1fr]">
            <span className={`flex h-10 w-10 items-center justify-center rounded-xl text-sm font-black ${step.completed ? "bg-emerald-100 text-emerald-800" : step.type === "experiment" ? "bg-sky-100 text-sky-800" : "bg-teal-50 text-teal-800"}`}>{step.completed ? <CheckCircleOutlined /> : step.order}</span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><h3 className="font-extrabold text-slate-900">{step.title}</h3><Tag color={step.type === "review" ? "orange" : step.type === "experiment" ? "blue" : "cyan"}>{step.type === "review" ? "前置回补" : step.type === "experiment" ? "参数实验" : "分层练习"}</Tag></div>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{step.reason}</p>
              <div className="mt-4 flex flex-wrap gap-2">{step.question_ids.map((id, index) => <Button key={id} size="small" onClick={() => navigate(`/questions?query=${id}&task=1`)}>{id}{step.difficulty[index] ? ` · ${step.difficulty[index]}` : ""}</Button>)}{step.experiment_id && <Button size="small" type="primary" ghost icon={<ExperimentOutlined />} onClick={() => navigate(`/experiments?id=${step.experiment_id}`)}>打开关联实验</Button>}</div>
            </div>
          </li>)}
        </ol>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-labelledby="warning-heading">
        <div className="border-b border-slate-200 px-6 py-5"><h2 id="warning-heading" className="flex items-center gap-2 text-lg font-extrabold text-slate-900"><WarningOutlined className="text-amber-600" />认知断层预警</h2><p className="mt-1 text-sm text-slate-600">只在至少有两次相关作答时发出，避免凭一次失误下结论。</p></div>
        {profile.alerts.length === 0 ? <Empty className="!my-10" image={Empty.PRESENTED_IMAGE_SIMPLE} description={noEvidence ? "完成诊断题后生成预警" : "暂未发现需要预警的知识断层"} /> : <div className="divide-y divide-slate-100">{profile.alerts.map(alert => <article key={`${alert.keypoint}-${alert.title}`} className="px-6 py-5">
          <div className="flex items-start justify-between gap-3"><h3 className="font-extrabold text-slate-900">{alert.title}</h3><Tag color={alert.severity === "high" ? "red" : alert.severity === "medium" ? "orange" : "blue"}>{alert.severity === "high" ? "高风险" : alert.severity === "medium" ? "需关注" : "提示"}</Tag></div>
          <p className="mt-2 text-sm leading-6 text-slate-600">{alert.message}</p>
          <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950"><span className="font-bold">建议：</span>{alert.recommendation}</div>
          <p className="mt-3 text-sm text-slate-500">证据：{alert.evidence.questions} 道题 · {alert.evidence.attempts} 次作答 · 使用 {alert.evidence.hints} 次提示</p>
        </article>)}</div>}
      </section>
    </div>

    <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-labelledby="mastery-heading">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-200 px-6 py-5"><div><h2 id="mastery-heading" className="flex items-center gap-2 text-lg font-extrabold text-slate-900"><SafetyCertificateOutlined className="text-teal-700" />知识点掌握度</h2><p className="mt-1 text-sm text-slate-600">掌握度反映表现，置信度反映证据是否充足，两者需一起看。</p></div>{profile.mastery.length > 8 && <Button type="link" onClick={() => setShowAll(value => !value)}>{showAll ? "收起" : `查看全部 ${profile.mastery.length} 个`}</Button>}</div>
      {visibleMastery.length === 0 ? <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center"><BookOutlined className="text-2xl text-slate-400" /><p className="mt-3 font-bold text-slate-700">还没有可计算的知识点</p><Button className="mt-2" type="link" onClick={() => navigate("/questions")}>去完成基础题</Button></div> : <div className="grid md:grid-cols-2">{visibleMastery.map(item => <button key={item.id + item.name} onClick={() => navigate(`/questions?keypoint=${encodeURIComponent(item.name)}`)} className="border-b border-slate-100 px-6 py-5 text-left transition hover:bg-teal-50/60 md:odd:border-r">
        <div className="flex items-center justify-between gap-3"><span className="font-extrabold text-slate-800">{item.name}</span><Tag color={item.status === "mastered" ? "green" : item.status === "developing" ? "blue" : "orange"}>{statusLabel[item.status]}</Tag></div>
        <Progress className="!mb-0 !mt-3" percent={item.score} size="small" strokeColor={item.status === "mastered" ? "#16a34a" : item.status === "at_risk" ? "#d97706" : "#0f766e"} />
        <div className="mt-2 flex flex-wrap justify-between gap-2 text-sm text-slate-500"><span>置信度 {item.confidence}% · {item.questions} 道题</span><span>{item.top_error ? `主要问题：${item.top_error}` : item.trend === "up" ? "趋势上升" : "表现稳定"}</span></div>
      </button>)}</div>}
    </section>
  </div>;
}
