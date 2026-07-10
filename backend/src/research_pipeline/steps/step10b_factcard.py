"""Step 10b — create a compact L1 fact card for future retrieval."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from ...integrations.llm_client import ChatMessage, LLMClient
from ..context import PipelineContext

COMPANY_LIB = Path(os.environ.get("COMPANY_LIB_PATH", str(Path.home() / "company_lib"))).expanduser()


async def run(ctx: PipelineContext) -> PipelineContext:
    if ctx.report_status == "insufficient" or not ctx.report_path or not Path(ctx.report_path).exists():
        return ctx
    report = Path(ctx.report_path).read_text(encoding="utf-8", errors="ignore")
    prompt = "将报告提炼为不超过600字的事实卡。必须包含：核心结论、关键数字、竞争格局、数据缺口。保留来源编号，不引入新事实。"
    try:
        card = await LLMClient(name="factcard").chat([ChatMessage("user", report[:50000])], system=prompt, max_tokens=2000)
        if card.lstrip().startswith("{"):
            return ctx
    except Exception:
        return ctx
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", ctx.clarified_text)[:60].strip("-") or "report"
    folder = COMPANY_LIB / "fact_cards"
    folder.mkdir(parents=True, exist_ok=True)
    content = f"---\nreport_type: {ctx.report_type}\ndate: {date.today().isoformat()}\nsource_report: {ctx.report_path}\n---\n\n{card.strip()}\n"
    (folder / f"_factcard_{date.today().strftime('%Y%m%d')}_{slug}.md").write_text(content, encoding="utf-8")
    return ctx
