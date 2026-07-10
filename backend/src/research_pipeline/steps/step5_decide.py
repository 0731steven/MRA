"""Step 5 — 覆盖决策：LLM 独立语义评估每个子问题的覆盖情况。

R6：不信任脚本的 sufficient 字段，LLM 独立评估。
R2：⚠️/❌ 必须补搜。
邻域方向不计入覆盖评分。
"""
from __future__ import annotations

from ..context import PipelineContext
from ...integrations.llm_client import LLMClient, ChatMessage

_SYSTEM = """你是 IC 设计领域的研究助手。

根据技术全景表和已有素材，评估每个子问题的覆盖情况。

覆盖规则（仅基于「核心」和「约束」类方向，「邻域」不计分）：
- ✅：该子问题有充分的核心+约束方向素材，可以写出完整答案
- ⚠️：有部分相关素材，但不够充分（如只有综述没有电路细节，或只覆盖一个方向）
- ❌：完全没有相关素材

决策规则：
- 所有子问题均 ✅ → decision_path = "step8"（跳过远程搜索）
- 任一 ⚠️ 或 ❌ → decision_path = "step6"（需补搜）

缺口 gaps 只列「核心」和「约束」类方向中 coverage=⚠️/❌ 的方向，
每个缺口给出 2-3 个针对性搜索词（英文）。

输出 JSON（不加 markdown 代码块）：
{
  "coverage": {"Q1": "✅", "Q2": "⚠️", "Q3": "❌"},
  "decision_path": "step6",
  "gaps": [
    {
      "direction": "LDO PSRR compensation techniques",
      "category": "核心",
      "keywords": ["LDO PSRR improvement", "power supply rejection ratio enhancement"]
    }
  ]
}"""


async def run(ctx: PipelineContext) -> None:
    if not ctx.panorama_table:
        # 无全景表：所有子问题标 ❌，盲补搜
        ctx.initial_coverage = {q.id: "❌" for q in ctx.sub_questions}
        for q in ctx.sub_questions:
            q.coverage = "❌"
        ctx.decision_path = "step6"
        # 缺口用关键词直接驱动
        ctx.gaps = [{"direction": kw, "category": "核心", "keywords": [kw]} for kw in ctx.keywords[:3]]
        return

    panorama_text = "\n".join(
        f"- {r.direction} [{r.category}] coverage={r.coverage} sources={r.mentioned_sources}"
        for r in ctx.panorama_table
    )
    sub_q_text = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)

    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题列表：\n{sub_q_text}\n\n"
        f"技术全景表：\n{panorama_text}"
    )

    llm = LLMClient(step=5)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_SYSTEM,
            max_tokens=1024,
        )
    except Exception:
        result = {
            "coverage": {q.id: "⚠️" for q in ctx.sub_questions},
            "decision_path": "step6",
            "gaps": [{"direction": kw, "category": "核心", "keywords": [kw]} for kw in ctx.keywords[:3]],
        }

    coverage = result.get("coverage", {})
    for q in ctx.sub_questions:
        q.coverage = coverage.get(q.id, "❌")
    ctx.initial_coverage = coverage
    ctx.decision_path = result.get("decision_path", "step6")
    ctx.gaps = result.get("gaps", [])

    # 把子问题覆盖结果回写进全景表：
    # 若某方向（核心/约束）对应的子问题中有 ⚠️/❌，则该行标注最低覆盖级别
    # 这样全景表在报告里能如实反映哪些方向素材不足
    if ctx.panorama_table:
        # 取所有 ⚠️/❌ 子问题的文本，让全景表行与之模糊匹配
        weak_qs = {q.id for q in ctx.sub_questions if q.coverage in ("⚠️", "❌")}
        weak_coverage = {q.id: q.coverage for q in ctx.sub_questions if q.id in weak_qs}
        # LLM 已在 gaps 里给出哪些方向缺口，用 direction 文本匹配全景表行
        gap_directions = {g.get("direction", "").lower() for g in ctx.gaps}
        for row in ctx.panorama_table:
            if row.category not in ("核心", "约束"):
                continue
            dir_lower = row.direction.lower()
            # 若该行方向出现在缺口列表里，降级为 ⚠️（若原来已是 ❌ 不升）
            if any(d and (d in dir_lower or dir_lower in d) for d in gap_directions):
                if row.coverage == "✅":
                    row.coverage = "⚠️"
