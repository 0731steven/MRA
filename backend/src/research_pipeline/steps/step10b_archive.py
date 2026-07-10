"""Step 10b — 问答精华存档到 wiki/qa/（免审核直写）。"""
from __future__ import annotations
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..context import PipelineContext

WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))
QA_DIR = WILSON_LIB / "wiki" / "qa"


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())[:40]


async def run(ctx: PipelineContext) -> None:
    if not ctx.report_path or ctx.report_type == "insufficient":
        return

    QA_DIR.mkdir(parents=True, exist_ok=True)

    # Store report_path as relative to WILSON_LIB for portable matching
    rp = Path(ctx.report_path)
    try:
        report_path_stored = rp.relative_to(WILSON_LIB).as_posix()
    except ValueError:
        report_path_stored = rp.as_posix()

    question = ctx.clarified_text or " ".join(ctx.keywords)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = _slug(question)
    qa_path = QA_DIR / f"{slug}_{date_str}_t{ctx.task_id}.md"

    # 生成摘要存档（不含原始文献，只含要点）
    panorama_text = "\n".join(
        f"- {r.direction} [{r.category}] {r.coverage}"
        for r in ctx.panorama_table
    )
    sub_q_text = "\n".join(f"- {q.id}: {q.text} → {q.coverage}" for q in ctx.sub_questions)

    content = f"""---
title: "{question[:80]}"
tags: [qa, {ctx.tier}]
created: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}
report_path: "{report_path_stored}"
---

# {question}

## 子问题覆盖

{sub_q_text}

## 技术全景

{panorama_text}

## 素材统计

- 本地文献: {len(ctx.local_candidates)} 篇
- IEEE 新论文: {len(ctx.ieee_new_papers)} 篇
- 专利: {len(ctx.patent_downloaded)} 项
- Web 归档: {len(ctx.web_archived)} 条
"""

    try:
        qa_path.write_text(content, encoding="utf-8")
        print(f"[Step 10b] 问答存档: {qa_path}")
    except Exception as e:
        print(f"[Step 10b] 存档失败: {e}")
