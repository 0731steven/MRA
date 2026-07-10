"""Step 8 — non-blocking Markdown/YAML/source validation."""
from __future__ import annotations

import re
from pathlib import Path

from ..context import PipelineContext
from ..report_templates import get_template


async def run(ctx: PipelineContext) -> PipelineContext:
    warnings: list[str] = []
    if not ctx.report_path or not Path(ctx.report_path).exists():
        warnings.append("报告文件不存在")
    else:
        text = Path(ctx.report_path).read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("---\n") or text.count("---") < 2:
            warnings.append("YAML frontmatter 不完整")
        for section in get_template(ctx.report_type)["sections"]:
            if f"## {section}" not in text:
                warnings.append(f"缺少章节：{section}")
        refs = {int(x) for x in re.findall(r"\[S(\d+)\]", text)}
        if refs and max(refs) > len(ctx.context_blocks):
            warnings.append("存在超出来源索引范围的引用")
        if re.search(r"\b(?:IEEE|CNIPA|wilson_lib)\b", text, flags=re.I):
            warnings.append("报告包含 IC-RA 遗留术语")
    ctx.qc_warnings = warnings
    return ctx
