"""Step 6 — normalize and rank KB, ME and Web evidence blocks."""
from __future__ import annotations

from pathlib import Path

from ...company_lib.retriever import build_context_blocks
from ..context import PipelineContext


async def run(ctx: PipelineContext) -> PipelineContext:
    query = " ".join([ctx.clarified_text, *ctx.keywords, *(q.text for q in ctx.sub_questions)])
    kb = build_context_blocks(ctx.kb_candidates, query)
    me = [{
        "source_type": "me",
        "source_id": f"{b.get('endpoint', '')}#{i}",
        "title": b.get("title", "ME 数据"),
        "content": b.get("content", ""),
        "evidence_slot": b.get("evidence_slot", "E4"),
        "url": b.get("source_url", ""),
        "published_at": b.get("published_at", ""),
    } for i, b in enumerate(ctx.me_data_blocks)]
    web: list[dict] = []
    for i, item in enumerate(ctx.web_archived):
        content = str(item.get("content", ""))
        path = item.get("path") or item.get("staging_path")
        if not content and path and Path(path).is_file():
            try:
                content = Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
        web.append({"source_type": "web", "source_id": f"web#{i}", "title": item.get("title", item.get("url", "Web 来源")), "content": content[:12000], "url": item.get("url", "")})
    order = {"kb_l1": 0, "me": 1, "kb": 2, "web": 3}
    combined = kb + me + web
    combined.sort(key=lambda x: order.get(x.get("source_type", ""), 9))
    seen: set[tuple[str, str]] = set()
    ctx.context_blocks = []
    for block in combined:
        key = (block.get("source_type", ""), block.get("source_id", ""))
        if key in seen or not block.get("content"):
            continue
        seen.add(key)
        ctx.context_blocks.append(block)
    return ctx
