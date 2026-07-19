import { useEffect, useState } from "react";
import { Alert, Button, DatePicker, Empty, Form, Input, InputNumber, Popconfirm, Progress, Select, Skeleton, Tag, message } from "antd";
import { CheckCircleOutlined, CopyOutlined, InboxOutlined, PlusOutlined, RadarChartOutlined, ReloadOutlined, SendOutlined, StopOutlined, SyncOutlined, TeamOutlined, UserDeleteOutlined, WarningOutlined } from "@ant-design/icons";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Classroom { id: number; name: string; course_name: string; join_code: string; members: number; assignments: number; status: "active" | "archived" }
interface RadarGroup { key: string; type: string; label: string; focus: string; student_ids: number[]; count: number; strategy: string }
interface Keypoint { name: string; mastery: number; confidence: number; students: number; at_risk: number; developing: number; mastered: number; top_error?: string; prerequisites: string[] }
interface StudentRow { id: number; name: string; overall_mastery: number; evidence_level: "low" | "medium" | "high"; attempts: number; questions: number; risk_keypoints: number; next_focus: string; top_error?: string; group_label: string; group_focus: string; independent_transfer: boolean }
interface Assignment { id: number; title: string; kind: string; topic: string; status: "published" | "cancelled" | "archived"; recipient_count: number; completed_count: number; question_ids: string[]; due_at?: string; created_at?: string }
interface Radar { classroom: Classroom; summary: { members: number; active_students: number; attempts: number; needs_intervention: number; independent_transfer: number }; keypoints: Keypoint[]; students: StudentRow[]; groups: RadarGroup[]; assignments: Assignment[] }

const kindLabel: Record<string, string> = { diagnostic: "诊断", intervention: "干预", retest: "迁移验证" };
const evidenceLabel = { low: "证据积累中", medium: "中等可信", high: "高可信" };

export default function ClassroomRadarPage() {
  const { user } = useAuth();
  const teacher = user?.role === "teacher";
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [selectedId, setSelectedId] = useState<number>();
  const [radar, setRadar] = useState<Radar | null>(null);
  const [loading, setLoading] = useState(true);
  const [radarLoading, setRadarLoading] = useState(false);
  const [error, setError] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [intervening, setIntervening] = useState(false);

  async function loadClassrooms(preferredId?: number) {
    setLoading(true);
    try {
      const response = await apiClient.get<Classroom[]>("/api/classrooms");
      setClassrooms(response.data);
      const next = preferredId || selectedId || response.data[0]?.id;
      setSelectedId(next);
      setError(false);
    } catch { setError(true); } finally { setLoading(false); }
  }

  async function loadRadar(id = selectedId) {
    if (!id) { setRadar(null); return; }
    setRadarLoading(true);
    try { const response = await apiClient.get<Radar>(`/api/classrooms/${id}/radar`); setRadar(response.data); setError(false); }
    catch { setError(true); } finally { setRadarLoading(false); }
  }

  useEffect(() => { if (teacher) void loadClassrooms(); }, [teacher]);
  useEffect(() => { if (selectedId) void loadRadar(selectedId); }, [selectedId]);

  if (!teacher) return <Alert type="warning" showIcon message="班级认知雷达仅供教师使用" description="学生可以在“我的任务”中加入班级并完成教师下发的任务。" />;

  async function createClass(values: { name: string; course_name?: string }) {
    setCreating(true);
    try {
      const response = await apiClient.post<Classroom>("/api/classrooms", values);
      message.success(`班级已创建，班级码为 ${response.data.join_code}`);
      setShowCreate(false);
      await loadClassrooms(response.data.id);
    } catch { message.error("班级创建失败，请保留名称并稍后重试"); } finally { setCreating(false); }
  }

  async function publishDiagnostic(values: { title?: string; topic: string; count: number; due_at?: { toISOString: () => string } }) {
    if (!selectedId) return;
    setPublishing(true);
    try {
      await apiClient.post(`/api/classrooms/${selectedId}/assignments`, { ...values, due_at: values.due_at?.toISOString() });
      message.success("诊断任务已发布给全班学生");
      await loadRadar(selectedId);
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "诊断任务发布失败，请稍后重试");
    } finally { setPublishing(false); }
  }

  async function createInterventions() {
    if (!selectedId) return;
    setIntervening(true);
    try {
      const response = await apiClient.post<{ groups: number; students: number }>(`/api/classrooms/${selectedId}/interventions`, { source_assignment_id: radar?.assignments[0]?.id });
      message.success(`已生成 ${response.data.groups} 组任务，覆盖 ${response.data.students} 名学生`);
      await loadRadar(selectedId);
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "干预任务生成失败，请稍后重试");
    } finally { setIntervening(false); }
  }

  async function copyCode() {
    const code = radar?.classroom.join_code;
    if (!code) return;
    try { await navigator.clipboard.writeText(code); message.success("班级码已复制"); }
    catch { message.info(`班级码：${code}`); }
  }

  async function regenerateCode() {
    if (!selectedId) return;
    try {
      const response = await apiClient.post<{ join_code: string }>(`/api/classrooms/${selectedId}/join-code`);
      message.success(`新班级码已生成：${response.data.join_code}`);
      await Promise.all([loadClassrooms(selectedId), loadRadar(selectedId)]);
    } catch { message.error("班级码更新失败，请稍后重试"); }
  }

  async function setClassroomStatus(status: "active" | "archived") {
    if (!selectedId) return;
    try {
      await apiClient.patch(`/api/classrooms/${selectedId}`, { status });
      message.success(status === "archived" ? "班级已归档，学生不能再通过班级码加入" : "班级已恢复，可以继续发布任务");
      await Promise.all([loadClassrooms(selectedId), loadRadar(selectedId)]);
    } catch { message.error("班级状态更新失败，请稍后重试"); }
  }

  async function removeStudent(studentId: number, studentName: string) {
    if (!selectedId) return;
    try {
      await apiClient.delete(`/api/classrooms/${selectedId}/members/${studentId}`);
      message.success(`${studentName} 已移出班级；既有作答证据仍会保留`);
      await Promise.all([loadClassrooms(selectedId), loadRadar(selectedId)]);
    } catch { message.error("移出学生失败，请稍后重试"); }
  }

  async function setAssignmentStatus(assignmentId: number, status: "published" | "cancelled" | "archived") {
    try {
      await apiClient.patch(`/api/assignments/${assignmentId}`, { status });
      message.success(status === "published" ? "任务已重新发布" : status === "cancelled" ? "任务已撤回，学生端不再显示" : "任务已归档");
      await loadRadar(selectedId);
    } catch { message.error("任务状态更新失败，请稍后重试"); }
  }

  function showDiagnosticForm() {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById("diagnostic-panel")?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    window.setTimeout(() => document.querySelector<HTMLInputElement>("#diagnostic-panel input")?.focus(), reducedMotion ? 0 : 250);
  }

  return <div className="mx-auto max-w-[1440px]">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-slate-950">班级认知雷达</h1><p className="mt-1 max-w-3xl text-base leading-7 text-slate-600">用班级任务证据识别共性断层，分组下发干预，并验证学生能否独立迁移。</p></div>
      <div className="flex flex-wrap gap-2"><Button icon={<ReloadOutlined />} onClick={() => loadRadar()} disabled={!selectedId} loading={radarLoading}>刷新证据</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(value => !value)}>创建班级</Button></div>
    </div>

    {showCreate && <section className="mt-5 border-y border-slate-200 bg-white px-5 py-5" aria-labelledby="create-class-heading"><h2 id="create-class-heading" className="mb-4 text-lg font-bold text-slate-900">创建一个课程班级</h2><Form layout="inline" onFinish={createClass} initialValues={{ course_name: "概率论与数理统计" }} className="gap-y-3"><Form.Item name="name" label="班级名称" rules={[{ required: true, message: "请输入班级名称" }]}><Input placeholder="如：2026级统计学1班" maxLength={160} /></Form.Item><Form.Item name="course_name" label="课程名称"><Input maxLength={160} /></Form.Item><Form.Item><Button type="primary" htmlType="submit" loading={creating}>创建并生成班级码</Button></Form.Item></Form></section>}

    {error && <Alert className="mt-5" type="error" showIcon message="班级数据暂时无法载入" description="请检查连接后重试；已保存的任务和作答不会丢失。" action={<Button size="small" onClick={() => loadClassrooms()}>重新加载</Button>} />}
    {loading ? <div className="mt-6"><Skeleton active paragraph={{ rows: 5 }} /></div> : classrooms.length === 0 ? <section className="mt-6 flex min-h-80 flex-col items-center justify-center border border-slate-200 bg-white px-6 text-center"><TeamOutlined className="text-3xl text-teal-700" /><h2 className="mt-4 text-lg font-bold text-slate-900">先创建第一个班级</h2><p className="mt-2 max-w-lg text-base leading-7 text-slate-600">学生使用班级码加入后，你就可以发布短诊断，并从真实作答证据生成班级认知雷达。</p><Button className="mt-5" type="primary" onClick={() => setShowCreate(true)}>创建班级</Button></section> : <>
      <section className="mt-6 flex flex-wrap items-center gap-4 border-y border-slate-200 bg-white px-5 py-4">
        <Select className="min-w-60" value={selectedId} onChange={setSelectedId} options={classrooms.map(item => ({ value: item.id, label: item.status === "archived" ? `${item.name}（已归档）` : item.name }))} aria-label="选择班级" />
        {radar && <><span className="text-sm text-slate-500">班级码</span><button onClick={copyCode} className="flex min-h-10 items-center gap-2 rounded-lg bg-slate-950 px-3 font-mono text-sm font-bold tracking-wider text-white"><span>{radar.classroom.join_code}</span><CopyOutlined /></button><span className="text-sm text-slate-500">{radar.classroom.status === "active" ? "学生输入此码即可加入" : "班级已归档，当前班级码不可加入"}</span><div className="ml-auto flex flex-wrap gap-2"><Popconfirm title="生成新班级码？" description="原班级码会立即失效，已加入的学生不受影响。" okText="生成" cancelText="取消" onConfirm={regenerateCode}><Button icon={<SyncOutlined />}>更换班级码</Button></Popconfirm>{radar.classroom.status === "active" ? <Popconfirm title="归档这个班级？" description="归档后不能加入或发布新任务，历史数据会保留。" okText="归档" cancelText="取消" onConfirm={() => setClassroomStatus("archived")}><Button icon={<InboxOutlined />}>归档班级</Button></Popconfirm> : <Button type="primary" icon={<ReloadOutlined />} onClick={() => setClassroomStatus("active")}>恢复班级</Button>}</div></>}
      </section>

      {radarLoading && !radar ? <div className="mt-6"><Skeleton active paragraph={{ rows: 10 }} /></div> : radar && <>
        {radar.classroom.status === "archived" && <Alert className="mt-5" type="warning" showIcon message="这个班级已归档" description="历史任务与作答证据仍然可查；恢复班级后才能邀请新学生、发布诊断或生成干预任务。" />}
        <section aria-label="班级证据概览" className="mt-6 grid overflow-hidden border border-slate-200 bg-white sm:grid-cols-2 lg:grid-cols-5 lg:divide-x lg:divide-slate-200">
          <Metric label="班级学生" value={radar.summary.members} note={`${radar.summary.active_students} 人已有作答证据`} />
          <Metric label="任务作答" value={radar.summary.attempts} note="仅统计当前班级任务" />
          <Metric label="需教师干预" value={radar.summary.needs_intervention} note="不含证据积累组" tone="warning" />
          <Metric label="独立迁移" value={radar.summary.independent_transfer} note="干预后无提示正确" tone="success" />
          <Metric label="已评估知识点" value={radar.keypoints.length} note="掌握度与置信度并列" last />
        </section>

        <section className="mt-4 grid gap-4 bg-slate-950 px-5 py-5 text-white sm:grid-cols-[1fr_auto] sm:items-center" aria-labelledby="next-action-heading">
          <div><h2 id="next-action-heading" className="text-lg font-bold">{radar.summary.members === 0 ? "下一步：邀请学生加入班级" : radar.summary.attempts === 0 ? "下一步：发布第一组短诊断" : radar.summary.needs_intervention > 0 ? `下一步：为 ${radar.summary.needs_intervention} 名学生下发分组干预` : "下一步：用迁移题验证稳定掌握"}</h2><p className="mt-1 text-sm leading-6 text-slate-300">{radar.summary.members === 0 ? "复制班级码并发给学生；加入后即可接收诊断任务。" : radar.summary.attempts === 0 ? "3—5 道题即可建立第一份班级证据，低证据不会被提前定性。" : "系统已根据当前证据给出动态分组；教师确认后再发布，分组不会成为固定能力标签。"}</p></div>
          {radar.summary.members === 0 ? <Button icon={<CopyOutlined />} onClick={copyCode} disabled={radar.classroom.status !== "active"}>复制班级码</Button> : radar.summary.attempts === 0 ? <Button type="primary" onClick={showDiagnosticForm} disabled={radar.classroom.status !== "active"}>填写诊断主题</Button> : <Button type="primary" loading={intervening} icon={<RadarChartOutlined />} onClick={createInterventions} disabled={radar.classroom.status !== "active"}>审核并下发任务</Button>}
        </section>

        <section id="diagnostic-panel" className="mt-6 border-y border-slate-200 bg-white" aria-labelledby="diagnostic-heading">
          <div className="grid gap-5 px-5 py-5 lg:grid-cols-[280px_1fr]"><div><h2 id="diagnostic-heading" className="text-lg font-bold text-slate-900">发布短诊断</h2><p className="mt-1 text-sm leading-6 text-slate-600">建议每次 3—5 题；系统会自动兼顾基础、提升和迁移证据。</p></div><Form layout="inline" onFinish={publishDiagnostic} initialValues={{ count: 5 }} className="gap-y-3" disabled={radar.classroom.status !== "active"}><Form.Item name="topic" label="知识点" rules={[{ required: true, message: "请输入知识点" }]}><Input placeholder="如：贝叶斯公式" maxLength={160} /></Form.Item><Form.Item name="title" label="任务名称"><Input placeholder="留空则自动命名" maxLength={180} /></Form.Item><Form.Item name="count" label="题数"><InputNumber min={1} max={8} /></Form.Item><Form.Item name="due_at" label="截止时间"><DatePicker showTime format="YYYY-MM-DD HH:mm" placeholder="可选" /></Form.Item><Form.Item><Button type="primary" htmlType="submit" loading={publishing} icon={<SendOutlined />}>发布给全班</Button></Form.Item></Form></div>
        </section>

        <div className="mt-8 grid items-start gap-5 xl:grid-cols-[1.18fr_.82fr]">
          <section className="overflow-hidden border border-slate-200 bg-white" aria-labelledby="keypoint-heading">
            <div className="border-b border-slate-200 px-5 py-4"><h2 id="keypoint-heading" className="text-lg font-bold text-slate-900">知识点风险</h2><p className="mt-1 text-sm text-slate-600">优先显示风险人数较多且掌握度较低的知识点。</p></div>
            {radar.keypoints.length === 0 ? <Empty className="!my-10" image={Empty.PRESENTED_IMAGE_SIMPLE} description="发布并完成第一组诊断后生成知识点风险" /> : <div className="divide-y divide-slate-100">{radar.keypoints.slice(0, 10).map(item => <div key={item.name} className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(150px,1fr)_180px_130px]"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-900">{item.name}</span>{item.at_risk > 0 && <Tag color="orange">{item.at_risk} 人需巩固</Tag>}</div><p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-600">{item.top_error ? `常见问题：${item.top_error}` : item.prerequisites.length ? `前置：${item.prerequisites.join("、")}` : "暂无集中错误类型"}</p></div><div><div className="mb-1 flex justify-between text-sm text-slate-600"><span>掌握度</span><span className="tabular-nums">{item.mastery}%</span></div><Progress percent={item.mastery} size="small" showInfo={false} strokeColor={item.mastery < 60 ? "#d97706" : "#0f766e"} /></div><div className="flex items-center justify-between gap-2 text-sm"><span className="text-slate-600">置信度</span><span className="font-semibold tabular-nums text-slate-800">{item.confidence}% · {item.students}人</span></div></div>)}</div>}
          </section>

          <section className="overflow-hidden border border-slate-200 bg-white" aria-labelledby="group-heading">
            <div className="border-b border-slate-200 px-5 py-4"><h2 id="group-heading" className="text-lg font-bold text-slate-900">建议干预分组</h2><p className="mt-1 text-sm text-slate-600">分组随新证据更新；主操作区会根据当前状态提示教师下一步。</p></div>
            {radar.groups.length === 0 ? <Empty className="!my-10" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可分组学生" /> : <div className="divide-y divide-slate-100">{radar.groups.map(group => <article key={group.key} className="px-5 py-4"><div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><h3 className="font-bold text-slate-900">{group.label}</h3><Tag color={group.type === "transfer_ready" ? "green" : group.type === "needs_diagnostic" ? "blue" : "orange"}>{group.count} 人</Tag></div><p className="mt-1 text-sm font-semibold text-teal-800">当前焦点：{group.focus}</p></div>{group.type === "transfer_ready" ? <CheckCircleOutlined className="text-lg text-emerald-600" /> : <WarningOutlined className="text-lg text-amber-600" />}</div><p className="mt-2 text-sm leading-6 text-slate-600">{group.strategy}</p></article>)}</div>}
          </section>
        </div>

        <section className="mt-8 overflow-hidden border border-slate-200 bg-white" aria-labelledby="student-heading">
          <div className="border-b border-slate-200 px-5 py-4"><h2 id="student-heading" className="text-lg font-bold text-slate-900">学生证据明细</h2><p className="mt-1 text-sm text-slate-600">低证据不会被标记为确定断层；分组名称描述当前任务，不定义学生能力。</p></div>
          {radar.students.length === 0 ? <Empty className="!my-10" image={Empty.PRESENTED_IMAGE_SIMPLE} description="班级还没有学生" /> : <div className="overflow-x-auto"><table className="w-full min-w-[960px] border-collapse text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="sticky left-0 z-10 bg-slate-50 px-5 py-3 font-semibold">学生</th><th className="px-4 py-3 font-semibold">当前分组</th><th className="px-4 py-3 font-semibold">下一焦点</th><th className="px-4 py-3 font-semibold">掌握度</th><th className="px-4 py-3 font-semibold">证据</th><th className="px-4 py-3 font-semibold">风险</th><th className="px-4 py-3 font-semibold">独立迁移</th><th className="px-5 py-3 font-semibold">成员操作</th></tr></thead><tbody className="divide-y divide-slate-100">{radar.students.map(student => <tr key={student.id} className="group hover:bg-slate-50"><td className="sticky left-0 bg-white px-5 py-3.5 font-semibold text-slate-900 group-hover:bg-slate-50">{student.name}</td><td className="px-4 py-3.5"><Tag color={student.group_label === "迁移挑战组" ? "green" : student.group_label === "证据积累组" ? "blue" : "orange"}>{student.group_label}</Tag></td><td className="px-4 py-3.5 text-slate-700">{student.group_focus || student.next_focus}</td><td className="px-4 py-3.5 font-semibold tabular-nums text-slate-800">{student.overall_mastery}%</td><td className="px-4 py-3.5"><span className="text-slate-700">{evidenceLabel[student.evidence_level]}</span><span className="ml-1 text-slate-600">· {student.questions}题</span></td><td className="px-4 py-3.5 text-slate-700">{student.risk_keypoints ? `${student.risk_keypoints}个知识点` : student.top_error || "暂无"}</td><td className="px-4 py-3.5">{student.independent_transfer ? <span className="font-semibold text-emerald-700"><CheckCircleOutlined className="mr-1" />已验证</span> : <span className="text-slate-600">待验证</span>}</td><td className="px-5 py-3.5"><Popconfirm title={`将 ${student.name} 移出班级？`} description="既有任务作答证据会保留，之后不再收到本班新任务。" okText="移出" cancelText="取消" onConfirm={() => removeStudent(student.id, student.name)}><Button danger type="text" icon={<UserDeleteOutlined />}>移出</Button></Popconfirm></td></tr>)}</tbody></table></div>}
        </section>

        <section className="mt-8 overflow-hidden border border-slate-200 bg-white" aria-labelledby="assignment-heading"><div className="border-b border-slate-200 px-5 py-4"><h2 id="assignment-heading" className="text-lg font-bold text-slate-900">最近任务</h2></div>{radar.assignments.length === 0 ? <Empty className="!my-8" image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有发布任务" /> : <div className="divide-y divide-slate-100">{radar.assignments.map(item => <div key={item.id} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-center"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-900">{item.title}</span><Tag>{kindLabel[item.kind] || item.kind}</Tag>{item.status !== "published" && <Tag color={item.status === "cancelled" ? "red" : "default"}>{item.status === "cancelled" ? "已撤回" : "已归档"}</Tag>}</div><p className="mt-1 text-sm text-slate-600">{item.question_ids.length} 道题 · {item.topic}{item.due_at ? ` · 截止 ${new Date(item.due_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""}</p></div><span className="text-sm text-slate-600">{item.completed_count}/{item.recipient_count} 人完成</span><Progress className="!mb-0 w-36" percent={item.recipient_count ? Math.round(item.completed_count / item.recipient_count * 100) : 0} size="small" showInfo={false} />{item.status === "published" ? <Popconfirm title="撤回这项任务？" description="学生端将不再显示，已有作答和完成进度会保留。" okText="撤回" cancelText="取消" onConfirm={() => setAssignmentStatus(item.id, "cancelled")}><Button danger type="text" icon={<StopOutlined />}>撤回</Button></Popconfirm> : <div className="flex gap-1"><Button type="link" onClick={() => setAssignmentStatus(item.id, "published")}>重新发布</Button>{item.status !== "archived" && <Button type="text" icon={<InboxOutlined />} onClick={() => setAssignmentStatus(item.id, "archived")}>归档</Button>}</div>}</div>)}</div>}</section>
      </>}
    </>}
  </div>;
}

function Metric({ label, value, note, tone = "default", last = false }: { label: string; value: number; note: string; tone?: "default" | "warning" | "success"; last?: boolean }) {
  const color = tone === "warning" ? "text-amber-700" : tone === "success" ? "text-emerald-700" : "text-slate-950";
  return <div className={`border-b border-slate-100 px-5 py-4 last:border-b-0 sm:odd:border-r lg:border-b-0 lg:odd:border-r-0 ${last ? "sm:col-span-2 lg:col-span-1" : ""}`}><p className="text-sm font-semibold text-slate-600">{label}</p><p className={`mt-1 text-xl font-bold tabular-nums ${color}`}>{value}</p><p className="mt-1 text-xs text-slate-600">{note}</p></div>;
}
