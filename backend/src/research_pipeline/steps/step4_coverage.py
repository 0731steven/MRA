"""Step 4 — assess evidence coverage against the selected report schema."""
from __future__ import annotations

import json

from ...integrations.llm_client import ChatMessage, LLMClient
from ..context import PipelineContext
from ..report_templates import get_template


async def run(ctx: PipelineContext) -> PipelineContext:
    template = get_template(ctx.report_type)
    evidence = [f"KB: {x.get('title', '')}" for x in ctx.local_candidates[:30]]
    evidence += [f"ME/{x.get('evidence_slot', '')}: {x.get('title', '')}\n{x.get('content', '')[:500]}" for x in ctx.me_data_blocks[:30]]
    prompt = {
        "question": ctx.clarified_text,
        "report_type": ctx.report_type,
        "sections": template["sections"],
        "core_sections": template["core"],
        "evidence": evidence,
    }
    system = """评估市场研究报告各章节的证据覆盖。仅输出 JSON：
{"sections":[{"section":"章节名","status":"✅/⚠️/❌","reason":"原因"}],"web_search_targets":["针对缺口的检索式"]}
不得因为常识而判定有覆盖，只有输入证据可计入。"""
    try:
        data = await LLMClient(step=4).chat_json([ChatMessage("user", json.dumps(prompt, ensure_ascii=False))], system=system, max_tokens=3000)
    except Exception:
        data = {}
    rows = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        has_any = bool(evidence)
        rows = [{"section": s, "status": "⚠️" if has_any else "❌", "reason": "自动回退评估"} for s in template["sections"]]
    normalized = []
    for section in template["sections"]:
        match = next((r for r in rows if isinstance(r, dict) and r.get("section") == section), {})
        status = match.get("status", "❌")
        if status not in {"✅", "⚠️", "❌"}:
            status = "❌"
        normalized.append({"section": section, "status": status, "reason": str(match.get("reason", ""))})
    ctx.section_coverage = normalized
    ctx.trigger_web_search = any(r["status"] == "❌" and r["section"] in template["core"] for r in normalized)
    targets = data.get("web_search_targets") if isinstance(data, dict) else []
    ctx.web_search_targets = [str(x) for x in targets if str(x).strip()][:8] if isinstance(targets, list) else []
    if ctx.trigger_web_search and not ctx.web_search_targets:
        ctx.web_search_targets = [f"{ctx.clarified_text} {r['section']} 2025 2026" for r in normalized if r["status"] == "❌" and r["section"] in template["core"]][:5]
    return ctx
