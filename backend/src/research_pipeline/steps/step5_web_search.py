"""Step 5 — conditional Web search using the legacy deterministic scripts."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ...integrations import cad_tools
from ..context import PipelineContext


async def run(ctx: PipelineContext) -> PipelineContext:
    if not ctx.trigger_web_search or ctx.tier == "quick":
        return ctx
    limit = 25 if ctx.report_type == "competitive" and ctx.tier == "deep" else 15 if ctx.report_type == "competitive" else 15 if ctx.tier == "deep" else 8
    candidates: list[dict] = []
    seen: set[str] = set()
    for target in ctx.web_search_targets[:5]:
        try:
            result = await cad_tools.web_search([target], max_results=limit, cdp_port=ctx.cdp_port)
        except Exception as exc:
            ctx.pipeline_warnings.append(f"Web 搜索失败：{exc}")
            continue
        rows = result.get("results", []) if isinstance(result, dict) else []
        for row in rows:
            url = str(row.get("url", ""))
            if url and url not in seen:
                seen.add(url)
                candidates.append(row)
    # Strict freshness: unknown year or older than previous calendar year is excluded.
    recent: list[dict] = []
    min_year = date.today().year - 1
    for row in candidates:
        blob = f"{row.get('title', '')} {row.get('date', '')} {row.get('snippet', '')}"
        years = [int(y) for y in re.findall(r"20\d{2}", blob)]
        if years and max(years) >= min_year:
            recent.append(row)
    selected = recent[:limit]
    if not selected:
        return ctx
    output = str(Path(ctx.staging_dir) / "web")
    try:
        result = await cad_tools.web_ingest([r["url"] for r in selected], ctx.keywords[0] if ctx.keywords else "mra", output, cdp_port=ctx.cdp_port)
    except Exception as exc:
        ctx.pipeline_warnings.append(f"Web 归档失败：{exc}")
        return ctx
    archived = result.get("archived", result.get("results", [])) if isinstance(result, dict) else []
    ctx.web_archived = archived if isinstance(archived, list) else []
    return ctx
