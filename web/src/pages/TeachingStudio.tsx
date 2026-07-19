import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Form, Input, InputNumber, Popconfirm, Result, Segmented, Select, Skeleton, Tag, message } from "antd";
import { BankOutlined, CheckCircleOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, FileTextOutlined, HistoryOutlined, ReadOutlined, SafetyCertificateOutlined, SaveOutlined, SendOutlined, TeamOutlined, WarningOutlined } from "@ant-design/icons";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/api/client";
import { MathMarkdown, markdownHeadingId } from "@/components/MathMarkdown";
import { useAuth } from "@/contexts/AuthContext";

type LayerKey = "foundation" | "progress" | "transfer";
type ViewKey = "teacher" | "student" | "insights" | "edit";

interface PackageLayer {
  label: string;
  fit: string;
  success: string;
  next: string;
  question_ids: string[];
}

interface PackageManifest {
  version: number;
  engine: string;
  lesson_type_label: string;
  learner_profile_label: string;
  classroom_name?: string | null;
  evidence_note: string;
  keypoints: string[];
  timeline: { phase: string; minutes: number; teacher_action: string; student_evidence: string }[];
  diagnostic_question_id: string;
  exit_ticket_question_id: string;
  layers: Record<LayerKey, PackageLayer>;
  quality_checks: { key: string; label: string; passed: boolean }[];
}

interface Plan {
  id: number;
  title: string;
  topic: string;
  duration: number;
  classroom_id?: number | null;
  lesson_type?: string;
  learner_profile?: string;
  question_ids: string[];
  content: string;
  student_content: string;
  package: PackageManifest;
  model?: string;
  updated_at?: string;
  layers?: Record<"易" | "中" | "难", string[]>;
  insights?: Insights;
}

interface Insights {
  keypoints: string[];
  prerequisites: Record<string, string[]>;
  layers: Record<"易" | "中" | "难", string[]>;
  diagnostics: { attempts: number; verdicts: Record<string, number>; error_types: { name: string; count: number }[] };
  warnings: { severity: "high" | "medium" | "low"; title: string; detail: string }[];
}

interface Classroom {
  id: number;
  name: string;
  members: number;
  assignments: number;
}

interface GenerateValues {
  topic: string;
  duration: number;
  classroom_id?: number;
  lesson_type: string;
  learner_profile: string;
  objectives?: string;
  question_ids?: string[];
}

const lessonTypes = [
  { value: "concept", label: "新授概念课" },
  { value: "review", label: "复习整合课" },
  { value: "remediation", label: "纠错补救课" },
  { value: "assessment", label: "诊断讲评课" },
];

const learnerProfiles = [
  { value: "mixed", label: "混合班级" },
  { value: "foundation", label: "需要更多脚手架" },
  { value: "advanced", label: "基础较稳，强调迁移" },
];

const publishSections = [
  { value: "diagnostic", label: "入门诊断" },
  { value: "foundation", label: "起步任务" },
  { value: "progress", label: "进阶任务" },
  { value: "transfer", label: "迁移挑战" },
  { value: "exit", label: "出门检测" },
];

export default function TeachingStudio() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const teacher = user?.role === "teacher";
  const [plans, setPlans] = useState<Plan[]>([]);
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [active, setActive] = useState<Plan | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [view, setView] = useState<ViewKey>("teacher");
  const [insights, setInsights] = useState<Insights | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [publishClassroomId, setPublishClassroomId] = useState<number>();
  const [publishSection, setPublishSection] = useState("diagnostic");
  const previewContent = useDeferredValue(content);

  useEffect(() => {
    if (!teacher) return;
    Promise.all([
      apiClient.get<Plan[]>("/api/question-bank/teaching-plans"),
      apiClient.get<Classroom[]>("/api/classrooms"),
    ]).then(([planResponse, classroomResponse]) => {
      setPlans(planResponse.data);
      setClassrooms(classroomResponse.data);
      setPlansError(false);
    }).catch(() => setPlansError(true)).finally(() => setPlansLoading(false));
  }, [teacher]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const selectedClassroom = useMemo(
    () => classrooms.find(item => item.id === publishClassroomId),
    [classrooms, publishClassroomId],
  );
  const outline = useMemo(() => {
    const source = view === "student" ? active?.student_content || "" : content;
    return [...source.matchAll(/^##\s+(.+)$/gm)].map(match => match[1].trim()).slice(0, 12);
  }, [active?.student_content, content, view]);

  if (!teacher) return <Result status="403" title="教师专属功能" subTitle="学生账号可以使用智能答疑和题库练习。" />;

  function selectPlan(plan: Plan) {
    if (dirty && active?.id !== plan.id) {
      message.warning("请先保存当前修改，再切换到其他教学包");
      return;
    }
    setActive(plan);
    setContent(plan.content);
    setView("teacher");
    setDirty(false);
    setInsights(null);
    setPublishClassroomId(plan.classroom_id || classrooms[0]?.id);
    void loadInsights(plan);
  }

  async function loadInsights(plan: Plan) {
    setInsightsLoading(true);
    try {
      const response = await apiClient.get<Insights>("/api/question-bank/teaching-insights", {
        params: {
          topic: plan.topic,
          question_ids: plan.question_ids.join(","),
          classroom_id: plan.classroom_id || undefined,
        },
      });
      setInsights(response.data);
    } catch {
      setInsights(null);
    } finally {
      setInsightsLoading(false);
    }
  }

  async function refreshPlans(preferredId?: number) {
    try {
      const response = await apiClient.get<Plan[]>("/api/question-bank/teaching-plans");
      setPlans(response.data);
      setPlansError(false);
      if (preferredId) {
        const plan = response.data.find(item => item.id === preferredId);
        if (plan) selectPlan(plan);
      }
    } catch (error) {
      setPlansError(true);
      throw error;
    }
  }

  async function submit(values: GenerateValues) {
    setLoading(true);
    try {
      const response = await apiClient.post<Plan>("/api/question-bank/teaching-plan", values);
      setActive(response.data);
      setContent(response.data.content);
      setView("teacher");
      setDirty(false);
      setInsights(response.data.insights || null);
      setPublishClassroomId(response.data.classroom_id || values.classroom_id || classrooms[0]?.id);
      try {
        await refreshPlans(response.data.id);
      } catch {
        message.warning("教学包已生成，但历史列表刷新失败");
      }
      message.success("教师执行版、学生学习单和证据报告已生成");
    } catch (error) {
      message.error(errorDetail(error, "教学包生成失败，请保留当前表单并稍后重试"));
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!active) return;
    setSaving(true);
    try {
      await apiClient.put(`/api/question-bank/teaching-plans/${active.id}`, { title: active.title, content });
      setActive({ ...active, content });
      setPlans(items => items.map(item => item.id === active.id ? { ...item, content } : item));
      setDirty(false);
      message.success("教师执行版修改已保存");
    } catch {
      message.error("保存失败，当前编辑内容仍保留在页面中");
    } finally {
      setSaving(false);
    }
  }

  async function remove(plan: Plan) {
    try {
      await apiClient.delete(`/api/question-bank/teaching-plans/${plan.id}`);
      if (active?.id === plan.id) {
        setActive(null);
        setContent("");
        setDirty(false);
        setInsights(null);
      }
      setPlans(items => items.filter(item => item.id !== plan.id));
      message.success("教学包已删除");
    } catch {
      message.error("删除失败，教学包仍然保留");
    }
  }

  function download() {
    if (!active) return;
    const studentVersion = view === "student";
    const downloadContent = studentVersion ? active.student_content : content;
    const blob = new Blob([downloadContent], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${active.topic.replace(/[\\/:*?"<>|]/g, "-")}-${studentVersion ? "学生学习单" : "教师执行版"}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function publishQuestionIds(plan: Plan): string[] {
    if (publishSection === "diagnostic") return [plan.package.diagnostic_question_id].filter(Boolean);
    if (publishSection === "exit") return [plan.package.exit_ticket_question_id].filter(Boolean);
    return plan.package.layers[publishSection as LayerKey]?.question_ids || [];
  }

  async function publish() {
    if (!active || !publishClassroomId) {
      message.warning("请先选择要发布的班级");
      return;
    }
    const questionIds = publishQuestionIds(active);
    if (!questionIds.length) {
      message.warning("当前层级没有可发布的题目，请重新生成或指定题号");
      return;
    }
    const sectionLabel = publishSections.find(item => item.value === publishSection)?.label || "课堂任务";
    setPublishing(true);
    try {
      await apiClient.post(`/api/classrooms/${publishClassroomId}/assignments`, {
        title: `${active.topic} · ${sectionLabel}`,
        topic: active.topic,
        question_ids: questionIds,
        count: questionIds.length,
        kind: publishSection === "exit" ? "retest" : publishSection === "diagnostic" ? "diagnostic" : "intervention",
        description: `来自教学包“${active.title}”。完成后作答证据将回写班级认知雷达。`,
      });
      message.success(`已向“${selectedClassroom?.name || "所选班级"}”发布 ${questionIds.length} 道题`);
    } catch (error) {
      message.error(errorDetail(error, "发布失败，请检查班级成员和题目配置"));
    } finally {
      setPublishing(false);
    }
  }

  return <div>
    <header className="mb-6">
      <h1 className="text-2xl font-black text-slate-900">分层教学包工作台</h1>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">从题库证据生成教师执行版、学生学习单和课堂检测，并把任一层级直接发布到班级。</p>
    </header>

    <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="space-y-5 xl:sticky xl:top-6 xl:self-start">
        <section className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="mb-5 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-lg text-teal-800"><ReadOutlined /></span>
            <div><h2 className="font-extrabold text-slate-900">生成教学包</h2><p className="text-sm text-slate-600">没有模型 Key 也能完整生成</p></div>
          </div>
          <Form layout="vertical" initialValues={{ duration: 45, lesson_type: "concept", learner_profile: "mixed" }} onFinish={submit} requiredMark={false}>
            <Form.Item name="topic" label="教学主题" rules={[{ required: true, message: "请输入教学主题" }, { max: 120, message: "教学主题请控制在 120 个字符以内" }]}>
              <Input size="large" maxLength={120} showCount placeholder="如：贝叶斯公式" />
            </Form.Item>
            <Form.Item name="classroom_id" label="关联班级（可选）" extra="关联后只读取该班级与所选题目相关的作答证据">
              <Select allowClear size="large" placeholder="先生成通用版" options={classrooms.map(item => ({ value: item.id, label: `${item.name} · ${item.members} 人` }))} />
            </Form.Item>
            <div className="grid grid-cols-2 gap-3">
              <Form.Item name="lesson_type" label="课堂类型"><Select size="large" options={lessonTypes} /></Form.Item>
              <Form.Item name="duration" label="时长（分钟）"><InputNumber size="large" min={15} max={180} className="!w-full" /></Form.Item>
            </div>
            <Form.Item name="learner_profile" label="学情基线"><Select size="large" options={learnerProfiles} /></Form.Item>
            <Form.Item name="question_ids" label="指定题号（可选）" rules={[{ validator: (_, values?: string[]) => !values?.some(value => !/^P\d{6}$/i.test(value.trim())) ? Promise.resolve() : Promise.reject(new Error("题号格式应为 P 加 6 位数字，如 P000001")) }]}>
              <Select mode="tags" size="large" tokenSeparators={[",", "，", " "]} placeholder="不填则按主题自动检索" open={false} maxTagCount="responsive" />
            </Form.Item>
            <Form.Item name="objectives" label="教师目标或限制条件"><Input.TextArea rows={3} maxLength={3000} showCount placeholder="如：学生会套公式，但常混淆条件概率方向…" /></Form.Item>
            <Button block type="primary" size="large" htmlType="submit" loading={loading} icon={<SendOutlined />}>生成三件套教学包</Button>
          </Form>
          <div className="mt-5 border-t border-slate-100 pt-4 text-sm text-slate-600">
            <p className="font-bold text-slate-800">一次生成</p>
            <ul className="mt-2 space-y-1.5">
              <li><CheckCircleOutlined className="mr-2 text-teal-700" />教师执行稿与分钟级流程</li>
              <li><CheckCircleOutlined className="mr-2 text-teal-700" />无答案学生学习单</li>
              <li><CheckCircleOutlined className="mr-2 text-teal-700" />题库溯源与认知风险报告</li>
            </ul>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="mb-4 flex items-center gap-2 font-extrabold text-slate-800"><HistoryOutlined className="text-teal-700" />历史教学包</div>
          <div className="max-h-80 overflow-y-auto">
            {plansLoading ? <div className="space-y-3"><Skeleton active paragraph={{ rows: 1 }} /><Skeleton active paragraph={{ rows: 1 }} /></div> : plansError && plans.length === 0 ? <Alert type="error" showIcon message="历史教学包加载失败" action={<Button size="small" onClick={() => { setPlansLoading(true); setPlansError(false); refreshPlans().catch(() => setPlansError(true)).finally(() => setPlansLoading(false)); }}>重试</Button>} /> : plans.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="填写主题，生成第一份可执行教学包" /> : <div className="divide-y divide-slate-100">{plans.map(plan => {
              const selected = active?.id === plan.id;
              return <div key={plan.id} className={`group flex items-center py-2.5 ${selected ? "bg-teal-50/70" : ""}`}>
                <button className="min-w-0 flex-1 rounded-lg px-2 py-1 text-left hover:bg-slate-50" onClick={() => selectPlan(plan)} aria-current={selected ? "true" : undefined}>
                  <span className={`block truncate text-sm font-bold ${selected ? "text-teal-950" : "text-slate-700"}`}>{plan.title}</span>
                  <span className="mt-1 block text-sm text-slate-600">{plan.question_ids.length} 道题 · {plan.duration} 分钟</span>
                </button>
                <Popconfirm title="删除这份教学包？" onConfirm={() => remove(plan)}><Button aria-label={`删除教学包：${plan.title}`} type="text" danger size="small" icon={<DeleteOutlined />} /></Popconfirm>
              </div>;
            })}</div>}
          </div>
        </section>
      </aside>

      <main className="min-h-[720px] overflow-hidden rounded-2xl border border-slate-200 bg-white">
        {loading ? <GeneratingState /> : active ? <>
          <div className="border-b border-slate-200 px-6 py-5 lg:px-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="truncate text-xl font-black text-slate-900">{active.title}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                  <Tag color="cyan">{active.package?.lesson_type_label || "教学包"}</Tag>
                  <span>{active.duration} 分钟</span><span aria-hidden="true">·</span><span>{active.question_ids.length} 道题</span>
                  <span aria-hidden="true">·</span><span>{active.package?.keypoints?.length || 0} 个核心知识点</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button icon={<SaveOutlined />} loading={saving} disabled={!dirty} onClick={save}>{dirty ? "保存修改" : "已保存"}</Button>
                <Button icon={<DownloadOutlined />} onClick={download}>导出{view === "student" ? "学生版" : "教师版"}</Button>
              </div>
            </div>
            <div className="mt-5 overflow-x-auto">
              <Segmented value={view} onChange={value => setView(value as ViewKey)} options={[
                { label: "教师执行版", value: "teacher", icon: <ReadOutlined /> },
                { label: "学生学习单", value: "student", icon: <FileTextOutlined /> },
                { label: "证据与风险", value: "insights", icon: <SafetyCertificateOutlined /> },
                { label: "编辑教师版", value: "edit", icon: <EditOutlined /> },
              ]} />
            </div>
          </div>

          <section className="grid gap-3 border-b border-slate-200 bg-slate-50 px-6 py-4 lg:grid-cols-[minmax(180px,1fr)_minmax(160px,220px)_auto] lg:items-end lg:px-8" aria-labelledby="publish-heading">
            <div><h3 id="publish-heading" className="text-sm font-extrabold text-slate-800"><BankOutlined className="mr-2 text-teal-700" />发布为班级任务</h3><p className="mt-1 text-sm text-slate-600">学生完成后，证据自动回写班级认知雷达。</p></div>
            <div className="flex gap-2">
              <Select aria-label="发布班级" className="min-w-0 flex-1" value={publishClassroomId} onChange={setPublishClassroomId} placeholder="选择班级" options={classrooms.map(item => ({ value: item.id, label: item.name }))} />
              <Select aria-label="发布教学包层级" className="min-w-32" value={publishSection} onChange={setPublishSection} options={publishSections} />
            </div>
            <Button type="primary" loading={publishing} disabled={!publishClassroomId} onClick={publish} icon={<TeamOutlined />}>发布任务</Button>
          </section>

          <div className="px-6 py-7 lg:px-9 lg:py-8">
            {view === "edit" ? <div>
              <Alert className="mb-5" type="info" showIcon message="左侧编辑 Markdown 源码，右侧实时查看排版结果" description="行内公式可用 $...$，独立公式可用 $$...$$；预览会自动兼容从题库或智能答疑导入的旧式公式分隔符。" />
              <div className="grid gap-5 xl:grid-cols-2">
                <section aria-labelledby="markdown-source-heading">
                  <div className="mb-3 flex items-center justify-between gap-3"><h3 id="markdown-source-heading" className="font-extrabold text-slate-800">Markdown 源码</h3><Tag>可编辑</Tag></div>
                  <Input.TextArea aria-label="编辑教师执行版内容" value={content} onChange={event => { setContent(event.target.value); setDirty(event.target.value !== active.content); }} autoSize={{ minRows: 28 }} maxLength={80000} className="!font-mono !text-sm !leading-7" />
                </section>
                <section aria-labelledby="formula-preview-heading" aria-busy={previewContent !== content} className="min-w-0 rounded-2xl border border-slate-200 bg-white">
                  <div className="sticky top-0 z-10 flex items-center justify-between gap-3 rounded-t-2xl border-b border-slate-200 bg-slate-50/95 px-5 py-3 backdrop-blur"><h3 id="formula-preview-heading" className="font-extrabold text-slate-800">公式与排版预览</h3><Tag color={previewContent === content ? "success" : "processing"}>{previewContent === content ? "已同步" : "更新中"}</Tag></div>
                  <div className="teaching-markdown max-h-[72vh] overflow-auto p-5 text-[15px] leading-8 text-slate-700"><MathMarkdown>{previewContent}</MathMarkdown></div>
                </section>
              </div>
            </div> : view === "insights" ? <InsightsPanel data={insights} packageData={active.package} loading={insightsLoading} onRetry={() => loadInsights(active)} /> : <>
              {view === "student" && <Alert className="mb-6" type="info" showIcon message="这是可直接发给学生的无答案版本" description="任务路径使用中性名称，不展示教师答案、讲评依据或班级风险判断。" />}
              {outline.length > 1 && <nav className="mb-6 rounded-2xl border border-slate-200 bg-slate-50 p-4" aria-label="教学包目录"><p className="text-sm font-extrabold text-slate-800">快速跳转</p><div className="mt-3 flex flex-wrap gap-2">{outline.map(heading => <a key={heading} href={`#${markdownHeadingId(heading)}`} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-teal-800 transition hover:border-teal-300 hover:bg-teal-50">{heading}</a>)}</div></nav>}
              <div className="teaching-markdown prose max-w-none text-[15px] leading-8 text-slate-700"><MathMarkdown>{view === "student" ? active.student_content : content}</MathMarkdown></div>
            </>}
          </div>
        </> : <EmptyTeachingState classrooms={classrooms} onGoClassrooms={() => navigate("/classrooms")} />}
      </main>
    </div>
  </div>;
}

function InsightsPanel({ data, packageData, loading, onRetry }: { data: Insights | null; packageData: PackageManifest; loading: boolean; onRetry: () => void }) {
  if (loading) return <div className="space-y-5"><Skeleton active paragraph={{ rows: 3 }} /><Skeleton active paragraph={{ rows: 6 }} /></div>;
  if (!data) return <Alert type="error" showIcon message="证据报告加载失败" description="教师版与学生版仍可使用；重试只会重新读取题库和班级证据。" action={<Button size="small" onClick={onRetry}>重试</Button>} />;
  const riskAttempts = (data.diagnostics.verdicts.incorrect || 0) + (data.diagnostics.verdicts.partial || 0);
  return <div>
    <Alert type={data.diagnostics.attempts ? "info" : "warning"} showIcon message={packageData.evidence_note} />
    <section className="mt-6" aria-labelledby="quality-heading">
      <h3 id="quality-heading" className="text-lg font-extrabold text-slate-900">生成质量检查</h3>
      <div className="mt-3 flex flex-wrap gap-2">{packageData.quality_checks.map(item => <Tag key={item.key} color={item.passed ? "success" : item.key === "class_evidence" ? "default" : "warning"} icon={item.passed ? <CheckCircleOutlined /> : <WarningOutlined />}>{item.label}</Tag>)}</div>
    </section>
    <div className="mt-6 grid overflow-hidden rounded-2xl border border-slate-200 sm:grid-cols-3 sm:divide-x sm:divide-slate-200">
      <Metric label="覆盖知识点" value={data.keypoints.length} note="来自当前教学包题目" />
      <Metric label="直接相关作答" value={data.diagnostics.attempts} note="不混入其他教师或其他班级" />
      <Metric label="未完全正确" value={riskAttempts} note="错误与部分正确作答" />
    </div>
    <section className="mt-7" aria-labelledby="timeline-heading">
      <h3 id="timeline-heading" className="text-lg font-extrabold text-slate-900">课堂时间闭合</h3>
      <div className="mt-3 divide-y divide-slate-100 border-y border-slate-200">{packageData.timeline.map(item => <div key={item.phase} className="grid gap-1 py-3 sm:grid-cols-[110px_80px_1fr]"><span className="font-bold text-slate-800">{item.phase}</span><span className="text-sm font-semibold text-teal-800">{item.minutes} 分钟</span><span className="text-sm text-slate-600">{item.teacher_action}</span></div>)}</div>
    </section>
    <section className="mt-7" aria-labelledby="layer-heading">
      <div><h3 id="layer-heading" className="text-lg font-extrabold text-slate-900">分层覆盖检查</h3><p className="mt-1 text-sm text-slate-600">层级是本节课的任务路径，可依据入门诊断动态调整。</p></div>
      <div className="mt-3 divide-y divide-slate-100 border-y border-slate-200">{Object.entries(packageData.layers).map(([key, layer]) => <div key={key} className="py-4 sm:flex sm:items-start sm:gap-4"><Tag color={key === "foundation" ? "green" : key === "progress" ? "orange" : "red"}>{layer.label}</Tag><div className="mt-2 min-w-0 flex-1 sm:mt-0"><p className="text-sm text-slate-700">{layer.success}</p><div className="mt-2 flex flex-wrap gap-2">{layer.question_ids.length ? layer.question_ids.map(id => <span key={id} className="rounded-lg bg-slate-100 px-2.5 py-1 text-sm font-semibold text-slate-700">{id}</span>) : <span className="text-sm font-semibold text-amber-700">当前缺题，发布前需补充</span>}</div></div></div>)}</div>
    </section>
    <section className="mt-7" aria-labelledby="risk-heading">
      <h3 id="risk-heading" className="flex items-center gap-2 text-lg font-extrabold text-slate-900"><SafetyCertificateOutlined className="text-teal-700" />认知断层与材料风险</h3>
      {data.warnings.length === 0 ? <Alert className="mt-4" type="success" showIcon message="当前教学包未发现明显结构性风险" /> : <div className="mt-4 divide-y divide-slate-100 border-y border-slate-200">{data.warnings.map((item, index) => <article key={`${item.title}-${index}`} className="flex gap-4 py-4"><span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100 ${item.severity === "high" ? "text-rose-700" : item.severity === "medium" ? "text-amber-700" : "text-sky-700"}`}><WarningOutlined /></span><div><div className="flex flex-wrap items-center gap-2"><h4 className="font-extrabold text-slate-800">{item.title}</h4><Tag color={item.severity === "high" ? "red" : item.severity === "medium" ? "orange" : "blue"}>{item.severity === "high" ? "高风险" : item.severity === "medium" ? "需关注" : "提示"}</Tag></div><p className="mt-1.5 text-sm leading-6 text-slate-600">{item.detail}</p></div></article>)}</div>}
    </section>
    {Object.keys(data.prerequisites).length > 0 && <section className="mt-7"><h3 className="text-lg font-extrabold text-slate-900">前置知识链</h3><div className="mt-3 divide-y divide-slate-100 border-y border-slate-200">{Object.entries(data.prerequisites).map(([target, prerequisites]) => <div key={target} className="flex flex-wrap items-center gap-2 py-3 text-sm"><span className="font-bold text-slate-700">{prerequisites.join("、")}</span><span className="text-slate-400">→</span><span className="font-extrabold text-teal-800">{target}</span></div>)}</div></section>}
  </div>;
}

function GeneratingState() {
  return <div className="mx-auto flex min-h-[680px] max-w-xl flex-col justify-center px-8">
    <p className="text-sm font-extrabold text-teal-800">正在构建三件套教学包</p>
    <h2 className="mt-2 text-xl font-black text-slate-900">检索题目、分配课堂时间并分离教师答案</h2>
    <div className="mt-7 space-y-4"><Skeleton active paragraph={{ rows: 2 }} /><Skeleton active paragraph={{ rows: 4 }} /><Skeleton active paragraph={{ rows: 3 }} /></div>
  </div>;
}

function EmptyTeachingState({ classrooms, onGoClassrooms }: { classrooms: Classroom[]; onGoClassrooms: () => void }) {
  return <div className="flex min-h-[680px] flex-col items-center justify-center px-8 text-center">
    <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-2xl text-slate-600"><ReadOutlined /></span>
    <h2 className="mt-5 text-lg font-extrabold text-slate-800">先生成一份可执行教学包</h2>
    <p className="mt-2 max-w-md text-sm leading-7 text-slate-600">只填写主题即可自动选题；关联班级后，还会把该班级与所选题目直接相关的作答证据写入教学决策。</p>
    {!classrooms.length && <Button className="mt-4" onClick={onGoClassrooms} icon={<BankOutlined />}>先创建班级</Button>}
  </div>;
}

function Metric({ label, value, note }: { label: string; value: number; note: string }) {
  return <div className="p-5"><p className="text-sm font-semibold text-slate-600">{label}</p><p className="mt-1 text-3xl font-black text-slate-900">{value}</p><p className="mt-1 text-sm text-slate-600">{note}</p></div>;
}

function errorDetail(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return fallback;
}
