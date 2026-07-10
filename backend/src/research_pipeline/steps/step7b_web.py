"""Step 7b — Web 补充搜索（quick 档跳过）。

两轮搜索 → LLM 评分 → web_ingest 归档 → 更新全景表。
"""
from __future__ import annotations
import json
from pathlib import Path

from ..context import PipelineContext
from ..tier import cfg
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

_SCORE_SYSTEM = """你是 IC 设计领域的研究助手。

评估以下 Web 搜索结果与子问题的相关性（1-5 分）。

优先选择：
- 原厂 application note / datasheet
- 权威博客/会议演讲
- 学术资料补充

降低权重：
- 论坛帖子、百科
- 付费墙页面（标注 paywall=true）

输出 JSON（不加 markdown 代码块）：
{
  "scores": [
    {"url": "https://...", "score": 4, "reason": "TI 应用笔记，直接给出 PSRR 优化方法", "mapped_questions": ["Q1"]}
  ]
}"""


async def run(ctx: PipelineContext) -> None:
    t = cfg(ctx.tier)
    if t["web_max"] == 0:
        return  # quick 档跳过

    max_archive = t["web_max"]
    kws = ctx.keywords[:4]
    topic = "_".join(kws[:2])

    seen_urls: dict[str, dict] = {}

    # 轮 1：宽泛
    try:
        r1 = await cad_tools.web_search(kws, max_archive * 3, cdp_port=ctx.cdp_port)
        for item in r1.get("results", []):
            url = item.get("url", "")
            if url:
                seen_urls[url] = item
    except Exception:
        pass

    # 轮 2：加 "application note" 限定
    try:
        r2 = await cad_tools.web_search(kws + ["application note"], max_archive * 2, cdp_port=ctx.cdp_port)
        for item in r2.get("results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls[url] = item
    except Exception:
        pass

    candidates = list(seen_urls.values())
    if not candidates:
        return

    # LLM 评分
    sub_q_text = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    cand_text = json.dumps(
        [{"url": c.get("url"), "title": c.get("title"), "snippet": c.get("snippet", "")[:200]}
         for c in candidates],
        ensure_ascii=False,
    )
    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题：\n{sub_q_text}\n\n"
        f"候选页面（JSON）：\n{cand_text}"
    )

    llm = LLMClient(step=7)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_SCORE_SYSTEM,
            max_tokens=2048,
        )
        scores = {s["url"]: s.get("score", 1) for s in result.get("scores", [])}
    except Exception:
        scores = {}

    for c in candidates:
        c["score"] = scores.get(c.get("url", ""), 1)

    selected_urls = [c["url"] for c in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
                     if c.get("score", 0) >= 3][:max_archive]

    if not selected_urls:
        return

    staging_web = str(Path(ctx.staging_dir) / "web") if ctx.staging_dir else ""
    if staging_web:
        Path(staging_web).mkdir(parents=True, exist_ok=True)

    try:
        await cad_tools.web_ingest(selected_urls, topic, staging_web or ".", cdp_port=ctx.cdp_port)
        ctx.web_archived = [{"url": u, "md_path": staging_web} for u in selected_urls]
        ctx.retry_counters["web"] = ctx.retry_counters.get("web", 0) + 1
    except Exception:
        pass
