const reportTypes = [
  ["📊", "市场研究", "市场规模、增长驱动、应用场景、竞争格局和南芯机会"],
  ["📦", "产品研究", "规格与功能对比、方案差异、产品定位和补齐建议"],
  ["⚔️", "竞品分析", "财务、新品、客户、技术和招聘信号及其对南芯的影响"],
  ["🔬", "技术研究", "技术路线、成熟度、产业采用、竞品布局和产品关联"],
];

const pipeline = [
  "识别报告类型，提取研究参数、关键词和子问题",
  "检索 company_lib 的 L1 事实卡与 L0 原始资料",
  "按报告类型只读查询 Market Engine",
  "评估章节覆盖度，对核心缺口按档位补充 Web 来源",
  "组装 KB、ME、Web 证据并执行写前数据检查",
  "三段式生成正文与执行摘要，所有事实使用来源编号",
  "执行质量评分、格式校验并生成可复用 Fact Card",
];

export default function GuidePage() {
  return (
    <div className="max-w-5xl mx-auto p-6 md:p-10">
      <div className="mb-8">
        <p className="text-xs font-bold tracking-[0.2em] text-indigo-500 uppercase mb-2">MRA Guide</p>
        <h1 className="text-3xl font-bold text-slate-900 mb-3">市场研究助手使用指南</h1>
        <p className="text-slate-500 leading-7 max-w-3xl">MRA 面向市场、战略和产品团队。系统只根据公司知识库、Market Engine 和公开 Web 证据写作；资料不足时会降级报告，不会补造数字或客户关系。</p>
      </div>

      <section className="bg-white/90 border border-slate-200 rounded-2xl p-6 mb-5 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4">四类报告</h2>
        <div className="grid md:grid-cols-2 gap-3">
          {reportTypes.map(([icon, title, desc]) => (
            <div key={title} className="rounded-xl border border-slate-100 bg-slate-50 p-4">
              <div className="font-semibold text-slate-800 mb-1">{icon} {title}</div>
              <div className="text-sm text-slate-500 leading-6">{desc}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-white/90 border border-slate-200 rounded-2xl p-6 mb-5 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4">一次请求如何运行</h2>
        <div className="space-y-3">
          {pipeline.map((item, i) => (
            <div key={item} className="flex gap-3 items-start">
              <span className="w-7 h-7 rounded-lg bg-indigo-600 text-white text-xs font-bold flex items-center justify-center shrink-0">{i + 1}</span>
              <p className="text-sm text-slate-600 leading-7 m-0">{item}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-white/90 border border-slate-200 rounded-2xl p-6 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4">档位与结果解读</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-500"><th className="py-3">档位</th><th>数据范围</th><th>适合场景</th></tr></thead>
            <tbody className="text-slate-600">
              <tr className="border-b border-slate-100"><td className="py-3 font-semibold">⚡ 快速</td><td>company_lib + ME，跳过 Web</td><td>已有内部资料的快速判断</td></tr>
              <tr className="border-b border-slate-100"><td className="py-3 font-semibold">📋 标准</td><td>对核心章节缺口补充 Web</td><td>日常市场和竞品研究</td></tr>
              <tr><td className="py-3 font-semibold">🔬 深度</td><td>扩大 Web 候选和证据数量</td><td>重要决策前的系统研究</td></tr>
            </tbody>
          </table>
        </div>
        <div className="mt-5 rounded-xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800 leading-6">
          <b>status=insufficient</b> 表示当前资料无法可靠支撑核心结论；质量卡中的“证据、覆盖、洞察、时效”用于判断报告能否直接用于决策。
        </div>
      </section>
    </div>
  );
}
