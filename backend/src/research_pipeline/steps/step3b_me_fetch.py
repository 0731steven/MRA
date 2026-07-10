"""Step 3b — read structured intelligence from Market Engine."""
from __future__ import annotations

from ...integrations.me_client import fetch_report_data
from ..context import PipelineContext


async def run(ctx: PipelineContext) -> PipelineContext:
    blocks, stats = await fetch_report_data(ctx.report_type, ctx.research_params, ctx.keywords)
    ctx.me_data_blocks = blocks
    ctx.me_fetch_stats = stats
    if stats.get("warning"):
        ctx.pipeline_warnings.append(str(stats["warning"]))
    return ctx
