"""Step 6b — deterministic evidence density and numeric support check."""
from __future__ import annotations

import re

from ..context import PipelineContext
from ..report_templates import get_template


async def run(ctx: PipelineContext) -> PipelineContext:
    text = "\n".join(str(b.get("content", "")) for b in ctx.context_blocks)
    numeric_hits = len(re.findall(r"(?<!\w)(?:\d+(?:\.\d+)?%?|\$\s?\d+|20\d{2})(?!\w)", text))
    source_types = sorted({b.get("source_type", "") for b in ctx.context_blocks})
    if not ctx.context_blocks:
        verdict = "insufficient"
    elif len(ctx.context_blocks) < 4 or numeric_hits < 3:
        verdict = "thin"
    else:
        verdict = "ok"
    uncovered = [r["section"] for r in ctx.section_coverage if r.get("status") == "❌"]
    ctx.retrieval_gaps = uncovered
    ctx.prewrite_coverage = {
        "verdict": verdict,
        "block_count": len(ctx.context_blocks),
        "numeric_hits": numeric_hits,
        "source_types": source_types,
        "uncovered_sections": uncovered,
        "summary_for_llm": f"数据基础={verdict}；证据块={len(ctx.context_blocks)}；数值证据={numeric_hits}；缺口={uncovered or '无'}。严禁补造缺失数据。",
    }
    if verdict == "insufficient":
        ctx.report_status = "insufficient"
    return ctx
