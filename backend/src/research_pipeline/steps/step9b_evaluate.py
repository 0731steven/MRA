"""Step 9b — report quality evaluation with deterministic fallback."""
from __future__ import annotations

import json
from pathlib import Path

from ...integrations.llm_client import ChatMessage, LLMClient
from ..context import PipelineContext


def _fallback(ctx: PipelineContext) -> dict:
    block_count = len(ctx.context_blocks)
    grounded = min(100, 25 + block_count * 6)
    covered = int(100 * sum(r.get("status") != "❌" for r in ctx.section_coverage) / max(len(ctx.section_coverage), 1))
    insight = 20 if ctx.report_status == "insufficient" else min(85, 35 + block_count * 4)
    freshness = 70 if any(b.get("source_type") in {"me", "web"} for b in ctx.context_blocks) else 40
    composite = round(grounded * .35 + covered * .30 + insight * .25 + freshness * .10, 1)
    return {"source_grounding": grounded, "sub_question_coverage": covered, "insight_density": insight, "data_freshness": freshness, "composite": composite, "method": "deterministic_fallback"}


async def run(ctx: PipelineContext) -> PipelineContext:
    report = Path(ctx.report_path).read_text(encoding="utf-8") if ctx.report_path else ""
    system = """对报告做质量评分，只输出 JSON。四项均为0-100整数：source_grounding、sub_question_coverage、insight_density、data_freshness，并给出 composite。不要因文笔好而提高证据评分。"""
    try:
        data = await LLMClient(name="eval").chat_json([ChatMessage("user", report[:50000])], system=system, max_tokens=1200)
        required = ["source_grounding", "sub_question_coverage", "insight_density", "data_freshness"]
        if not isinstance(data, dict) or not all(isinstance(data.get(k), (int, float)) for k in required):
            raise ValueError("invalid score payload")
        data["composite"] = round(data["source_grounding"] * .35 + data["sub_question_coverage"] * .30 + data["insight_density"] * .25 + data["data_freshness"] * .10, 1)
    except Exception:
        data = _fallback(ctx)
    ctx.eval_scores = data
    if data.get("sub_question_coverage", 0) < 40:
        ctx.report_status = "insufficient"
    if ctx.report_path:
        path = Path(ctx.report_path)
        content = path.read_text(encoding="utf-8")
        card = ("\n> **报告质量评分**："
                f"证据 {data.get('source_grounding')}/100 · 覆盖 {data.get('sub_question_coverage')}/100 · "
                f"洞察 {data.get('insight_density')}/100 · 时效 {data.get('data_freshness')}/100 · 综合 {data.get('composite')}/100\n")
        marker = "---\n\n# "
        content = content.replace(marker, f"---\n{card}\n# ", 1)
        if ctx.report_status == "insufficient":
            content = content.replace("status: complete", "status: insufficient", 1)
        path.write_text(content, encoding="utf-8")
    return ctx
