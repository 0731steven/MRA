import { AxiosHeaders, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

export const isDemoMode = import.meta.env.VITE_STATIC_PREVIEW === "true";
export const DEMO_ROLE_KEY = "mra-demo-role";
const DEMO_STATE_KEY = "mra-demo-state-v1";

type DemoRole = "student" | "teacher";

const questions = [
  { ID: "P000001", qtype: "简答题", hard_level: "易", keypoint: ["样本空间", "随机事件"], question: "抛掷一枚均匀硬币两次，写出样本空间，并指出事件“至少出现一次正面”包含哪些样本点。", choices: null, answer: "$\\Omega=\\{HH,HT,TH,TT\\}$，事件 $A=\\{HH,HT,TH\\}$。", explanation: "按两次抛掷的先后次序列举所有可能结果，再筛选至少含有一个 $H$ 的样本点。", can_reveal: true, teacher_view: true },
  { ID: "P000082", qtype: "计算题", hard_level: "中", keypoint: ["条件概率", "全概率公式"], question: "某工厂三条生产线的产量占比分别为 $0.2,0.3,0.5$，次品率分别为 $1\\%,2\\%,3\\%$。随机抽取一件产品，求它是次品的概率。", choices: null, answer: "$P(D)=0.2\\times0.01+0.3\\times0.02+0.5\\times0.03=0.023$。", explanation: "将生产线作为完备事件组，使用全概率公式对各来源的次品概率加权。", can_reveal: true, teacher_view: true },
  { ID: "P000206", qtype: "计算题", hard_level: "中", keypoint: ["贝叶斯公式", "条件概率"], question: "某疾病患病率为 $1\\%$，检测灵敏度为 $95\\%$，特异度为 $90\\%$。某人检测阳性，求其实际患病概率。", choices: null, answer: "$P(D\\mid +)=\\frac{0.01\\times0.95}{0.01\\times0.95+0.99\\times0.10}\\approx0.0876$。", explanation: "分母必须同时包含真阳性与假阳性。低患病率下，即使检测较准，阳性的后验概率也可能不高。", can_reveal: true, teacher_view: true },
  { ID: "P000311", qtype: "判断题", hard_level: "易", keypoint: ["随机变量", "分布函数"], question: "随机变量的分布函数一定是连续函数。", choices: null, answer: "错误。", explanation: "分布函数右连续，但可能存在跳跃；离散型随机变量的分布函数通常是阶梯函数。", can_reveal: true, teacher_view: true },
  { ID: "P000405", qtype: "计算题", hard_level: "中", keypoint: ["二项分布", "数学期望"], question: "设 $X\\sim B(20,0.3)$，求 $E(X)$ 与 $D(X)$。", choices: null, answer: "$E(X)=np=6$，$D(X)=np(1-p)=4.2$。", explanation: "二项分布的期望和方差分别为 $np$ 与 $np(1-p)$。", can_reveal: true, teacher_view: true },
  { ID: "P000512", qtype: "计算题", hard_level: "中", keypoint: ["正态分布", "标准化"], question: "若 $X\\sim N(10,4)$，求 $P(X\\le 12)$，结果可用标准正态分布函数表示。", choices: null, answer: "$P(X\\le12)=\\Phi(1)$。", explanation: "这里标准差为 $2$，标准化得到 $Z=(12-10)/2=1$。", can_reveal: true, teacher_view: true },
  { ID: "P000614", qtype: "简答题", hard_level: "中", keypoint: ["大数定律", "频率"], question: "说明大数定律中“频率趋近概率”的含义，并指出它是否意味着试验次数增加时误差单调减小。", choices: null, answer: "频率依概率收敛到事件概率，但单次样本路径上的误差不保证单调减小。", explanation: "收敛描述的是偏差超过给定阈值的概率趋于零，不是每增加一次试验误差都变小。", can_reveal: true, teacher_view: true },
  { ID: "P000737", qtype: "证明题", hard_level: "难", keypoint: ["中心极限定理", "样本均值"], question: "设 $X_1,\\ldots,X_n$ 独立同分布，均值为 $\\mu$、方差为 $\\sigma^2$。写出样本均值的中心极限定理标准化形式。", choices: null, answer: "$\\frac{\\sqrt n(\\bar X-\\mu)}{\\sigma}\\xrightarrow{d}N(0,1)$。", explanation: "先利用 $E(\\bar X)=\\mu$、$D(\\bar X)=\\sigma^2/n$，再按标准差 $\\sigma/\\sqrt n$ 标准化。", can_reveal: true, teacher_view: true },
  { ID: "P000801", qtype: "计算题", hard_level: "中", keypoint: ["置信区间", "参数估计"], question: "总体方差已知时，写出正态总体均值的 $95\\%$ 置信区间。", choices: null, answer: "$\\bar X\\pm1.96\\frac{\\sigma}{\\sqrt n}$。", explanation: "双侧 $95\\%$ 置信区间对应标准正态分位数 $z_{0.975}=1.96$。", can_reveal: true, teacher_view: true },
  { ID: "P000886", qtype: "多选题", hard_level: "中", keypoint: ["假设检验", "第一类错误"], question: "关于显著性水平 $\\alpha$，下列说法正确的是哪些？", choices: ["(1) 它控制第一类错误概率", "(2) 越小越容易拒绝原假设", "(3) 通常在检验前给定", "(4) 它就是第二类错误概率"], answer: "(1)、(3)。", explanation: "$\\alpha$ 是原假设为真时错误拒绝它的概率上界，通常在观察数据前确定。", can_reveal: true, teacher_view: true },
  { ID: "P000942", qtype: "简答题", hard_level: "易", keypoint: ["相关系数", "协方差"], question: "相关系数为零是否意味着两个随机变量相互独立？说明理由。", choices: null, answer: "一般不意味着独立；独立通常推出不相关，反向不成立。", explanation: "在联合正态等附加条件下，不相关才可推出独立。", can_reveal: true, teacher_view: true },
  { ID: "P001007", qtype: "计算题", hard_level: "难", keypoint: ["最大似然估计", "参数估计"], question: "设总体服从参数为 $\\lambda$ 的指数分布，给出 $\\lambda$ 的最大似然估计。", choices: null, answer: "$\\hat\\lambda=1/\\bar X$。", explanation: "写出似然函数并取对数，对 $\\lambda$ 求导后令其为零。", can_reveal: true, teacher_view: true },
];

const stats = {
  total: 1007,
  qtypes: { "简答题": 264, "计算题": 421, "判断题": 118, "多选题": 96, "证明题": 108 },
  difficulties: { "易": 338, "中": 469, "难": 200 },
  keypoints: { "样本空间": 62, "条件概率": 84, "贝叶斯公式": 46, "随机变量": 97, "二项分布": 58, "正态分布": 76, "大数定律": 35, "中心极限定理": 49, "置信区间": 52, "假设检验": 71, "相关系数": 43, "参数估计": 65 },
};

const classrooms = [
  { id: 1, name: "2026级统计学1班", course_name: "概率论与数理统计", join_code: "DEMO731", members: 32, assignments: 6, status: "active" },
  { id: 2, name: "数据科学实验班", course_name: "概率论与数理统计", join_code: "LAB2026", members: 24, assignments: 4, status: "active" },
];

const studentTasks = [
  { id: 101, classroom_id: 1, classroom_name: "2026级统计学1班", title: "条件概率课前诊断", description: "先独立完成，不使用提示；系统会据此安排后续任务。", kind: "diagnostic", topic: "条件概率", question_ids: ["P000001", "P000082", "P000206"], attempted_questions: 1, my_status: "assigned", due_at: "2026-08-01T12:00:00Z" },
  { id: 102, classroom_id: 1, classroom_name: "2026级统计学1班", title: "贝叶斯方向辨析", description: "针对条件方向混淆进行去提示练习。", kind: "intervention", topic: "贝叶斯公式", question_ids: ["P000082", "P000206"], attempted_questions: 0, my_status: "assigned", group_label: "概念巩固组" },
  { id: 99, classroom_id: 1, classroom_name: "2026级统计学1班", title: "随机变量基础检测", kind: "diagnostic", topic: "随机变量", question_ids: ["P000311", "P000405"], attempted_questions: 2, my_status: "completed" },
];

const learningSummary = {
  sessions: 6, questions_seen: 18, assistant_answers: 14, attempts: 21, attempted_questions: 12, correct_questions: 8,
  focus_keypoints: [{ name: "条件概率", count: 7 }, { name: "贝叶斯公式", count: 5 }, { name: "正态分布", count: 4 }, { name: "中心极限定理", count: 3 }],
  recent_sessions: [{ id: 2, title: "贝叶斯公式为什么要考虑先验概率", updated_at: "2026-07-23T08:30:00Z" }],
};

const learningProfile = {
  summary: { overall_mastery: 68, assessed_keypoints: 6, strong_keypoints: 2, risk_keypoints: 2, next_focus: "条件概率方向", evidence_level: "high" },
  evidence: { attempts: 21, questions: 12, keypoints: 6 },
  mastery: [
    { id: "kp-1", name: "样本空间", score: 88, confidence: 86, status: "mastered", trend: "up", attempts: 4, questions: 3, hint_count: 0 },
    { id: "kp-2", name: "条件概率", score: 54, confidence: 82, status: "at_risk", trend: "down", attempts: 6, questions: 4, hint_count: 3, top_error: "条件方向混淆" },
    { id: "kp-3", name: "贝叶斯公式", score: 61, confidence: 76, status: "developing", trend: "up", attempts: 4, questions: 3, hint_count: 2, top_error: "忽略先验率" },
    { id: "kp-4", name: "二项分布", score: 81, confidence: 73, status: "mastered", trend: "steady", attempts: 3, questions: 2, hint_count: 0 },
    { id: "kp-5", name: "正态分布", score: 69, confidence: 58, status: "developing", trend: "up", attempts: 2, questions: 2, hint_count: 1 },
    { id: "kp-6", name: "中心极限定理", score: 47, confidence: 55, status: "at_risk", trend: "steady", attempts: 2, questions: 2, hint_count: 2, top_error: "标准化尺度错误" },
  ],
  alerts: [
    { severity: "high", keypoint: "条件概率", title: "条件方向存在稳定混淆", message: "最近 4 道相关题中有 3 次把 $P(A\\mid B)$ 与 $P(B\\mid A)$ 互换。", recommendation: "先用树状图标清条件，再完成两道不带提示的方向辨析题。", evidence: { attempts: 6, questions: 4, hints: 3, top_error: "条件方向混淆" } },
    { severity: "medium", keypoint: "中心极限定理", title: "样本均值标准化仍需巩固", message: "能识别正态近似，但两次把标准差写成 $\\sigma/n$。", recommendation: "结合中心极限定理实验，观察样本量与均值波动的关系。", evidence: { attempts: 2, questions: 2, hints: 2, top_error: "标准化尺度错误" } },
  ],
  path: [
    { order: 1, type: "review", title: "辨清条件的方向", keypoint: "条件概率", reason: "这是贝叶斯公式的直接前置，且已有多次稳定错误证据。", question_ids: ["P000082", "P000206"], difficulty: ["中", "中"], completed: false },
    { order: 2, type: "experiment", title: "用参数实验理解先验率", keypoint: "贝叶斯公式", reason: "调节患病率，观察相同检测结果下后验概率如何变化。", question_ids: ["P000206"], difficulty: ["中"], experiment_id: "bayes", completed: false },
    { order: 3, type: "practice", title: "完成无提示迁移", keypoint: "中心极限定理", reason: "在新题型中正确使用 $\\sigma/\\sqrt n$ 完成标准化。", question_ids: ["P000737"], difficulty: ["难"], completed: false },
  ],
};

const radar = {
  classroom: classrooms[0],
  summary: { members: 32, active_students: 29, attempts: 126, needs_intervention: 9, independent_transfer: 14 },
  keypoints: [
    { name: "条件概率", mastery: 58, confidence: 84, students: 29, at_risk: 8, developing: 12, mastered: 9, top_error: "把条件与结果方向互换", prerequisites: ["样本空间", "乘法公式"] },
    { name: "贝叶斯公式", mastery: 63, confidence: 79, students: 27, at_risk: 6, developing: 11, mastered: 10, top_error: "忽略先验率与假阳性", prerequisites: ["条件概率", "全概率公式"] },
    { name: "二项分布", mastery: 76, confidence: 72, students: 25, at_risk: 3, developing: 8, mastered: 14, prerequisites: ["独立重复试验"] },
  ],
  groups: [
    { key: "foundation", type: "remediation", label: "前置回补组", focus: "条件概率方向", student_ids: [1, 2, 3, 4], count: 4, strategy: "用频数表和树状图重建条件事件，再完成两题即时反馈。" },
    { key: "concept", type: "practice", label: "概念巩固组", focus: "先验率", student_ids: [5, 6, 7, 8, 9], count: 5, strategy: "对比两组不同先验率的数据，解释同一阳性结果为何含义不同。" },
    { key: "transfer", type: "transfer_ready", label: "迁移挑战组", focus: "复杂情境建模", student_ids: [10, 11, 12, 13, 14], count: 14, strategy: "进入无提示的新情境题，验证能否独立识别完备事件组。" },
  ],
  students: [
    { id: 1, name: "林晨", overall_mastery: 52, evidence_level: "high", attempts: 8, questions: 5, risk_keypoints: 2, next_focus: "条件概率", top_error: "方向混淆", group_label: "前置回补组", group_focus: "条件概率方向", independent_transfer: false },
    { id: 2, name: "周然", overall_mastery: 64, evidence_level: "medium", attempts: 6, questions: 4, risk_keypoints: 1, next_focus: "贝叶斯公式", group_label: "概念巩固组", group_focus: "先验率", independent_transfer: false },
    { id: 3, name: "陈宇", overall_mastery: 83, evidence_level: "high", attempts: 9, questions: 6, risk_keypoints: 0, next_focus: "综合应用", group_label: "迁移挑战组", group_focus: "复杂情境建模", independent_transfer: true },
    { id: 4, name: "许诺", overall_mastery: 75, evidence_level: "medium", attempts: 5, questions: 4, risk_keypoints: 0, next_focus: "无提示迁移", group_label: "迁移挑战组", group_focus: "复杂情境建模", independent_transfer: true },
  ],
  assignments: [
    { id: 101, title: "条件概率课前诊断", kind: "diagnostic", topic: "条件概率", status: "published", recipient_count: 32, completed_count: 27, question_ids: ["P000001", "P000082", "P000206"], due_at: "2026-08-01T12:00:00Z", created_at: "2026-07-20T08:00:00Z" },
    { id: 102, title: "贝叶斯方向辨析", kind: "intervention", topic: "贝叶斯公式", status: "published", recipient_count: 9, completed_count: 5, question_ids: ["P000082", "P000206"], created_at: "2026-07-22T08:00:00Z" },
    { id: 98, title: "随机变量基础检测", kind: "retest", topic: "随机变量", status: "archived", recipient_count: 32, completed_count: 31, question_ids: ["P000311", "P000405"], created_at: "2026-07-10T08:00:00Z" },
  ],
};

const insights = {
  keypoints: ["条件概率", "全概率公式", "贝叶斯公式"],
  prerequisites: { "条件概率": ["样本空间", "乘法公式"], "贝叶斯公式": ["条件概率", "全概率公式"] },
  layers: { "易": ["P000001"], "中": ["P000082", "P000206"], "难": ["P000737"] },
  diagnostics: { attempts: 126, verdicts: { correct: 78, partial: 22, incorrect: 26 }, error_types: [{ name: "条件方向混淆", count: 18 }, { name: "忽略先验率", count: 11 }] },
  warnings: [{ severity: "high", title: "条件方向是主要共性断层", detail: "29 名有证据学生中，8 人出现两次以上方向混淆。" }],
};

const demoPlan = {
  id: 1, title: "贝叶斯公式 · 45分钟分层教学包", topic: "贝叶斯公式", duration: 45, classroom_id: 1, lesson_type: "concept", learner_profile: "mixed",
  question_ids: ["P000001", "P000082", "P000206", "P000737"],
  content: "# 贝叶斯公式 · 教师执行版\n\n## 学习目标\n\n1. 区分 $P(A\\mid B)$ 与 $P(B\\mid A)$。\n2. 能从完备事件组出发写出分母。\n3. 能解释先验率对后验概率的影响。\n\n## 课堂流程\n\n- **0—5 分钟**：用 P000082 快速诊断条件方向。\n- **5—15 分钟**：频数表解释真阳性与假阳性。\n- **15—30 分钟**：分层完成 P000206。\n- **30—40 分钟**：小组比较不同先验率。\n- **40—45 分钟**：无提示出门检测。\n\n## 教师提示\n\n先让学生说清“已知什么、求什么”，再写公式，避免直接套用。",
  student_content: "# 贝叶斯公式 · 学生学习单\n\n## 任务一：写清条件\n\n对 P000082 标出已知事件与目标事件。\n\n## 任务二：构造分母\n\n用树状图列出真阳性和假阳性两条路径。\n\n## 出门检测\n\n独立完成 P000206，并用一句话解释先验率的作用。",
  package: {
    version: 1, engine: "course-rules-v1", lesson_type_label: "新授概念课", learner_profile_label: "混合班级", classroom_name: "2026级统计学1班", evidence_note: "基于当前班级 126 次任务作答生成。", keypoints: ["条件概率", "全概率公式", "贝叶斯公式"],
    timeline: [
      { phase: "快速诊断", minutes: 5, teacher_action: "投放条件方向辨析题", student_evidence: "独立写出目标条件概率" },
      { phase: "概念建构", minutes: 10, teacher_action: "用频数表解释分母", student_evidence: "标出真阳性和假阳性" },
      { phase: "分层练习", minutes: 25, teacher_action: "按证据分配任务", student_evidence: "提交过程与解释" },
      { phase: "迁移检测", minutes: 5, teacher_action: "投放无提示题", student_evidence: "独立完成出门票" },
    ],
    diagnostic_question_id: "P000082", exit_ticket_question_id: "P000206",
    layers: {
      foundation: { label: "起步任务", fit: "条件方向仍混淆", success: "能正确标记已知与所求", next: "进入进阶任务", question_ids: ["P000001", "P000082"] },
      progress: { label: "进阶任务", fit: "会写公式但分母不完整", success: "能列出全部来源", next: "进入迁移挑战", question_ids: ["P000206"] },
      transfer: { label: "迁移挑战", fit: "基础较稳", success: "能在新情境独立建模", next: "完成无提示验证", question_ids: ["P000737"] },
    },
    quality_checks: [{ key: "time", label: "课堂时间闭合", passed: true }, { key: "trace", label: "题目可追溯", passed: true }, { key: "separation", label: "师生版本分离", passed: true }],
  },
  model: "course-rules-v1", updated_at: "2026-07-23T09:30:00Z", layers: { "易": ["P000001"], "中": ["P000082", "P000206"], "难": ["P000737"] }, insights,
};

const sessions = [
  { id: 2, title: "贝叶斯公式为什么要考虑先验概率", mode: "answer", created_at: "2026-07-22T08:00:00Z", updated_at: "2026-07-23T08:30:00Z" },
  { id: 1, title: "推荐条件概率基础题", mode: "recommend", created_at: "2026-07-20T08:00:00Z", updated_at: "2026-07-20T08:12:00Z" },
];

const sessionMessages = {
  2: { session: sessions[0], messages: [
    { id: 1, role: "user", content: "贝叶斯公式为什么要考虑先验概率？" },
    { id: 2, role: "assistant", content: "因为同一个观测结果，在不同基础发生率下含义不同。\\n\\n以检测阳性为例，后验概率为：\\n\\n$$P(D\\mid +)=\\frac{P(+\\mid D)P(D)}{P(+\\mid D)P(D)+P(+\\mid \\bar D)P(\\bar D)}$$\\n\\n其中 $P(D)$ 就是先验率。它决定真阳性在人群中的基础数量。", sources: [questions[2]], model: "demo" },
  ] },
  1: { session: sessions[1], messages: [
    { id: 3, role: "user", content: "推荐条件概率基础题" },
    { id: 4, role: "assistant", content: "建议按 P000001 → P000082 → P000206 的顺序练习：先列样本空间，再用全概率公式，最后进入贝叶斯公式。", sources: [questions[0], questions[1], questions[2]], model: "demo" },
  ] },
};

const experimentCatalog = [
  { experiment_id: "coin", keypoints: ["大数定律", "频率"], question_ids: ["P000614"] },
  { experiment_id: "binomial", keypoints: ["二项分布"], question_ids: ["P000405"] },
  { experiment_id: "normal", keypoints: ["正态分布"], question_ids: ["P000512"] },
  { experiment_id: "clt", keypoints: ["中心极限定理"], question_ids: ["P000737"] },
  { experiment_id: "bayes", keypoints: ["贝叶斯公式", "条件概率"], question_ids: ["P000206"] },
  { experiment_id: "confidence", keypoints: ["置信区间"], question_ids: ["P000801"] },
  { experiment_id: "montecarlo", keypoints: ["随机模拟"], question_ids: ["P000614"] },
  { experiment_id: "poisson", keypoints: ["泊松近似", "二项分布"], question_ids: ["P000405"] },
];

interface DemoState {
  classrooms: typeof classrooms;
  plans: typeof demoPlan[];
}

function initialState(): DemoState {
  return JSON.parse(JSON.stringify({ classrooms, plans: [demoPlan] })) as DemoState;
}

function loadState(): DemoState {
  try {
    const raw = localStorage.getItem(DEMO_STATE_KEY);
    return raw ? JSON.parse(raw) as DemoState : initialState();
  } catch {
    return initialState();
  }
}

function saveState(state: DemoState) {
  localStorage.setItem(DEMO_STATE_KEY, JSON.stringify(state));
}

export function resetDemoData() {
  localStorage.removeItem(DEMO_STATE_KEY);
}

export function demoUser(role: DemoRole) {
  return role === "teacher"
    ? { id: 7001, name: "演示教师", avatar_url: null, role: "teacher" as const }
    : { id: 7002, name: "演示学生", avatar_url: null, role: "student" as const };
}

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { data, status, statusText: status === 200 ? "OK" : "Created", headers: new AxiosHeaders(), config };
}

function body(config: InternalAxiosRequestConfig): Record<string, unknown> {
  if (!config.data) return {};
  if (typeof config.data === "string") {
    try { return JSON.parse(config.data) as Record<string, unknown>; } catch { return {}; }
  }
  return config.data as Record<string, unknown>;
}

function questionList(config: InternalAxiosRequestConfig) {
  const params = (config.params || {}) as Record<string, string | number | undefined>;
  const query = String(params.query || "").trim().toLowerCase();
  const qtype = String(params.qtype || "");
  const difficulty = String(params.difficulty || "");
  const keypoint = String(params.keypoint || "");
  const filtered = questions.filter(item =>
    (!query || item.ID.toLowerCase().includes(query) || item.question.toLowerCase().includes(query) || item.keypoint.some(value => value.toLowerCase().includes(query))) &&
    (!qtype || item.qtype === qtype) &&
    (!difficulty || item.hard_level === difficulty) &&
    (!keypoint || item.keypoint.includes(keypoint))
  );
  return { items: filtered, total: filtered.length, page: 1, page_size: 12 };
}

export const demoAdapter: AxiosAdapter = async config => {
  await new Promise(resolve => window.setTimeout(resolve, 90));
  const url = config.url || "";
  const method = (config.method || "get").toLowerCase();
  const state = loadState();

  if (url === "/api/question-bank/stats") return response(config, stats);
  if (url === "/api/question-bank/learning-summary") return response(config, learningSummary);
  if (url === "/api/question-bank/learning-profile") return response(config, learningProfile);
  if (url === "/api/question-bank/experiments/catalog") return response(config, experimentCatalog);
  if (url === "/api/question-bank/experiments/runs" && method === "post") return response(config, { id: Date.now() }, 201);
  if (url === "/api/question-bank/questions" && method === "get") return response(config, questionList(config));

  const answerMatch = url.match(/^\/api\/question-bank\/questions\/(P\d{6})\/answer$/i);
  if (answerMatch) return response(config, questions.find(item => item.ID === answerMatch[1].toUpperCase()) || questions[0]);
  const hintMatch = url.match(/^\/api\/question-bank\/questions\/(P\d{6})\/hint$/i);
  if (hintMatch) return response(config, { hint: "先写清楚已知事件和目标事件，再判断分母是否需要把所有可能来源相加。" });
  const attemptMatch = url.match(/^\/api\/question-bank\/questions\/(P\d{6})\/attempts$/i);
  if (attemptMatch) return response(config, { verdict: "partial", feedback: "你的方向是对的。下一步请把分母中的所有可能来源写完整，并检查条件概率的方向。", error_type: "条件方向需确认", attempt_no: 2, assignment_completed: true }, 201);
  const questionMatch = url.match(/^\/api\/question-bank\/questions\/(P\d{6})$/i);
  if (questionMatch) return response(config, questions.find(item => item.ID === questionMatch[1].toUpperCase()) || questions[0]);

  if (url === "/api/classrooms" && method === "get") return response(config, state.classrooms);
  if (url === "/api/classrooms" && method === "post") {
    const values = body(config);
    const created = { id: Date.now(), name: String(values.name || "新演示班级"), course_name: String(values.course_name || "概率论与数理统计"), join_code: "NEW2026", members: 0, assignments: 0, status: "active" as const };
    state.classrooms.unshift(created);
    saveState(state);
    return response(config, created, 201);
  }
  if (url === "/api/classrooms/join" && method === "post") return response(config, { name: "2026级统计学1班" });
  if (url === "/api/assignments/mine") return response(config, studentTasks);
  if (/^\/api\/classrooms\/\d+\/radar$/.test(url)) return response(config, { ...radar, classroom: state.classrooms.find(item => item.id === Number(url.split("/")[3])) || radar.classroom });
  if (/^\/api\/classrooms\/\d+\/interventions$/.test(url)) return response(config, { groups: 3, students: 9 }, 201);
  if (/^\/api\/classrooms\/\d+\/join-code$/.test(url)) return response(config, { join_code: "NEW731A" });
  if (/^\/api\/classrooms\/\d+\/assignments$/.test(url)) return response(config, { id: Date.now(), status: "published" }, 201);
  if (/^\/api\/(classrooms|assignments)\//.test(url)) return response(config, { ok: true });

  if (url === "/api/question-bank/teaching-plans" && method === "get") return response(config, state.plans);
  if (url === "/api/question-bank/teaching-insights") return response(config, insights);
  if (url === "/api/question-bank/teaching-plan" && method === "post") {
    const values = body(config);
    const created = { ...demoPlan, id: Date.now(), title: `${String(values.topic || "条件概率")} · ${Number(values.duration || 45)}分钟分层教学包`, topic: String(values.topic || "条件概率"), duration: Number(values.duration || 45) };
    state.plans.unshift(created);
    saveState(state);
    return response(config, created, 201);
  }
  const planMatch = url.match(/^\/api\/question-bank\/teaching-plans\/(\d+)$/);
  if (planMatch && method === "delete") {
    state.plans = state.plans.filter(item => item.id !== Number(planMatch[1]));
    saveState(state);
    return response(config, { ok: true });
  }
  if (planMatch) return response(config, { ok: true });

  if (url === "/api/question-bank/sessions") return response(config, sessions);
  const messagesMatch = url.match(/^\/api\/question-bank\/sessions\/(\d+)\/messages$/);
  if (messagesMatch) return response(config, sessionMessages[Number(messagesMatch[1]) as keyof typeof sessionMessages] || sessionMessages[2]);
  if (/^\/api\/question-bank\/sessions\/\d+$/.test(url)) return response(config, { ok: true });

  if (url === "/api/auth/me") {
    const role = (localStorage.getItem(DEMO_ROLE_KEY) || "student") as DemoRole;
    return response(config, demoUser(role));
  }
  if (url.startsWith("/api/auth/")) return response(config, { ok: true });

  return response(config, { ok: true });
};

export const demoTutorSources = questions.slice(0, 3).map(({ ID, qtype, question, keypoint, hard_level }) => ({ ID, qtype, question, keypoint, hard_level }));

export function demoTutorAnswer(message: string, mode: string, guidanceMode: string) {
  if (mode === "recommend") {
    return "我从演示题库中为你安排了 3 道题：\n\n1. **P000001**：用样本空间建立事件意识（易）\n2. **P000082**：使用全概率公式整合不同来源（中）\n3. **P000206**：进入贝叶斯后验概率（中）\n\n建议按顺序独立作答；遇到困难时先使用一次提示。";
  }
  const prefix = guidanceMode === "hint" ? "先给你一个关键提示" : guidanceMode === "check" ? "我们先检查思路" : guidanceMode === "full" ? "下面给出完整演示解析" : "我们分三步来理解";
  return `${prefix}：\n\n1. **写清条件**：贝叶斯问题里要先区分 $P(A\\mid B)$ 与 $P(B\\mid A)$。\n2. **补全分母**：分母代表观测结果发生的全部路径，通常需要全概率公式。\n3. **代入先验**：基础发生率 $P(A)$ 会直接影响后验概率。\n\n以 P000206 为例：\n\n$$P(D\\mid +)=\\frac{P(+\\mid D)P(D)}{P(+\\mid D)P(D)+P(+\\mid \\bar D)P(\\bar D)}$$\n\n你刚才的问题“${message.slice(0, 36)}”可以先从标出已知事件和目标事件开始。`;
}
