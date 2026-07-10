"""Step 3 — retrieve company knowledge-base candidates."""
from __future__ import annotations

from ...company_lib.retriever import retrieve_candidates
from ..context import PipelineContext


async def run(ctx: PipelineContext) -> PipelineContext:
    query = " ".join([ctx.clarified_text, *ctx.keywords, *(q.text for q in ctx.sub_questions)])
    ctx.kb_candidates = retrieve_candidates(query, ctx.report_type, ctx.research_params)
    ctx.local_candidates = [
        {k: v for k, v in item.items() if k != "content"}
        for item in ctx.kb_candidates
    ]
    ctx.has_core_materials = bool(ctx.kb_candidates)
    return ctx
