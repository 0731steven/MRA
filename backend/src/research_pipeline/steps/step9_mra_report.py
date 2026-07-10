"""Step 9 — grounded, three-call MRA report generation."""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from ...integrations.llm_client import ChatMessage, LLMClient
from ..context import PipelineContext
from ..report_templates import get_template

COMPANY_LIB = Path(os.environ.get("COMPANY_LIB_PATH", str(Path.home() / "company_lib"))).expanduser()


def _slug(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "-", text).strip("-")
    return value[:72] or "mra-report"


def _evidence(ctx: PipelineContext) -> str:
    parts = []
    for index, block in enumerate(ctx.context_blocks, 1):
        source = block.get("path") or block.get("url") or block.get("source_id")
        parts.append(f"[S{index}] {block.get('source_type')} | {block.get('title')} | {source}\n{block.get('content', '')}")
    return "\n\n".join(parts)


def _fallback_body(ctx: PipelineContext) -> str:
    template = get_template(ctx.report_type)
    lines = []
    for section in template["sections"]:
        lines.extend([f"## {section}", "", "当前证据不足，无法形成可靠结论。请补充内部知识库材料或启用 Market Engine 真实接口。", ""])
    return "\n".join(lines)


def _sources(ctx: PipelineContext) -> str:
    lines = ["## 来源索引", ""]
    if not ctx.context_blocks:
        return "## 来源索引\n\n- 暂无可用来源。"
    for i, block in enumerate(ctx.context_blocks, 1):
        source = block.get("path") or block.get("url") or block.get("source_id")
        lines.append(f"- [S{i}] {block.get('title', '未命名来源')}（{block.get('source_type')}）：{source}")
    return "\n".join(lines)


async def run(ctx: PipelineContext) -> PipelineContext:
    template = get_template(ctx.report_type)
    title = ctx.clarified_text.strip().splitlines()[0][:80] or f"{template['label']}报告"
    evidence = _evidence(ctx)
    profile_path = COMPANY_LIB / "_our_company_profile.md"
    profile = profile_path.read_text(encoding="utf-8", errors="ignore")[:16000] if profile_path.exists() else "南芯半导体（Southchip）视角；缺少公司画像时不要臆测内部组织和产品信息。"
    system = f"""你是南芯半导体市场情报分析师。生成{template['label']}报告。
硬约束：只能使用编号证据 [S1] 等；每个数字和事实结论后必须标来源；缺失数据明确写“数据缺失”；事实与推断分开；不得编造市场份额、财务数据、客户关系或内部计划。
南芯画像：\n{profile}
写前检查：{ctx.prewrite_coverage.get('summary_for_llm', '')}
章节：{json.dumps(template['sections'], ensure_ascii=False)}"""
    body = ""
    summary = ""
    if evidence:
        client = LLMClient(step=9)
        try:
            split = max(1, len(template["sections"]) // 2)
            first, second = template["sections"][:split], template["sections"][split:]
            part_a = await client.chat([ChatMessage("user", f"问题：{ctx.clarified_text}\n研究参数：{json.dumps(ctx.research_params, ensure_ascii=False)}\n请只写这些章节：{first}\n\n证据：\n{evidence}")], system=system, max_tokens=12000)
            part_b = await client.chat([ChatMessage("user", f"问题：{ctx.clarified_text}\n已写前半部分：\n{part_a}\n请只写这些章节：{second}\n\n证据：\n{evidence}")], system=system, max_tokens=12000)
            summary = await client.chat([ChatMessage("user", f"基于以下正文写 5-8 条执行摘要，每条必须保留来源编号；只输出摘要正文。\n{part_a}\n{part_b}")], system=system, max_tokens=4000)
            if part_a.lstrip().startswith("{") or part_b.lstrip().startswith("{"):
                raise ValueError("mock/non-markdown response")
            body = f"{part_a.strip()}\n\n{part_b.strip()}"
        except Exception as exc:
            ctx.pipeline_warnings.append(f"报告 LLM 生成回退：{exc}")
    if not body:
        ctx.report_status = "insufficient"
        summary = "现有证据不足，报告仅列出需补充的数据范围，未生成未经证据支持的判断。"
        body = _fallback_body(ctx)

    yaml = "\n".join([
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
        f"report_type: {ctx.report_type}",
        f"status: {ctx.report_status}",
        f"generated_at: {date.today().isoformat()}",
        f"kb_docs: {sum(1 for b in ctx.context_blocks if str(b.get('source_type', '')).startswith('kb'))}",
        f"me_signals: {sum(1 for b in ctx.context_blocks if b.get('source_type') == 'me')}",
        f"web_pages: {sum(1 for b in ctx.context_blocks if b.get('source_type') == 'web')}",
        "---",
    ])
    toc = "## 目录\n\n" + "\n".join(f"- {s}" for s in template["sections"])
    report = f"{yaml}\n\n# {title}\n\n## 执行摘要\n\n{summary.strip()}\n\n{toc}\n\n{body}\n\n{_sources(ctx)}\n"
    output_dir = COMPANY_LIB / "generated" / ctx.report_type
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{_slug(title)}_{date.today().strftime('%Y%m%d')}.md"
    output.write_text(report, encoding="utf-8")
    ctx.report_path = str(output)
    ctx.preflight_passed = True
    return ctx
