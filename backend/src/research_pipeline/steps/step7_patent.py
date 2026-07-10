"""Step 7 — 专利两段式检索（Google Patents，无登录要求）。

两轮搜索 → LLM 评分 → 下载 → patent_convert → 增量更新全景表。
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path

from ..context import PipelineContext
from ..tier import cfg
from .step6_ieee import _score_candidates as _score, _update_panorama, _gap_keywords
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

WILSON_LIB_PATH = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))



_SCORE_SYSTEM = """你是 IC 设计领域的研究助手。

评估以下专利候选与子问题的相关性（1-5 分）。

评分标准：
5 — 直接对应某子问题的解决方案
4 — 高度相关
3 — 部分相关
2 — 相关性低
1 — 不相关

输出 JSON（不加 markdown 代码块）：
{
  "scores": [
    {
      "patent_number": "CN1234567A",
      "score": 4,
      "reason": "LDO 环路补偿专利",
      "mapped_questions": ["Q1"]
    }
  ]
}"""


def _split_keywords(keywords: list[str]) -> list[list[str]]:
    """将关键词列表拆分为 ≤3 词的子列表（CNIPA 限制）。"""
    chunks: list[list[str]] = []
    for i in range(0, len(keywords), 3):
        chunk = keywords[i: i + 3]
        if chunk:
            chunks.append(chunk)
    return chunks or [keywords[:3]]


async def _search_all_chunks(keyword_chunks: list[list[str]], max_results: int, cdp_port: int | None = None) -> list[dict]:
    """并行搜索多个关键词组，合并去重。"""
    t0 = time.perf_counter()
    print(f"\n[step7] ── 搜索阶段 ──────────────────────────────────────────", flush=True)
    print(f"[step7] 关键词组: {keyword_chunks}  max={max_results}", flush=True)
    tasks = [cad_tools.patent_search_candidates(chunk, max_results, cdp_port=cdp_port) for chunk in keyword_chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen: dict[str, dict] = {}
    n_err = 0
    for r in results:
        if isinstance(r, Exception):
            n_err += 1
            print(f"[step7] chunk 搜索出错: {type(r).__name__}: {r}", flush=True)
            continue
        for p in r.get("patents", r.get("results", [])):
            num = p.get("patent_number", "")
            if num and num not in seen:
                seen[num] = p
    if n_err == len(results):
        print(f"[step7] 全部 {n_err} 个 chunk 失败 — Chrome CDP 未启动或 patent_search.py 崩溃", flush=True)
    elapsed = time.perf_counter() - t0
    candidates = list(seen.values())
    print(f"[step7] 搜索完成: 共 {len(candidates)} 篇候选  errors={n_err}/{len(results)}  耗时={elapsed:.1f}s", flush=True)
    for i, p in enumerate(candidates, 1):
        print(f"[step7]   {i:2d}. {p.get('patent_number',''):15s}  {p.get('title','')[:60]}", flush=True)
    return candidates


async def _score_patents(candidates: list[dict], ctx: PipelineContext) -> list[dict]:
    if not candidates:
        return []
    sub_q_text = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    cand_text = json.dumps(
        [{"patent_number": p.get("patent_number"), "title": p.get("title"), "abstract": p.get("abstract", "")[:300]}
         for p in candidates],
        ensure_ascii=False,
    )
    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题：\n{sub_q_text}\n\n"
        f"候选专利（JSON）：\n{cand_text}"
    )
    llm = LLMClient(step=7)
    t0 = time.perf_counter()
    print(f"\n[step7] ── 评分阶段 ──────────────────────────────────────────", flush=True)
    print(f"[step7] LLM 评分 {len(candidates)} 篇候选...", flush=True)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_SCORE_SYSTEM,
            max_tokens=2048,
        )
        scores = {s["patent_number"]: s for s in result.get("scores", [])}
        print(f"[step7] 评分完成: {len(scores)} 条  耗时={time.perf_counter()-t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"[step7] LLM 评分出错 耗时={time.perf_counter()-t0:.1f}s: {type(exc).__name__}: {exc}", flush=True)
        scores = {}
    for p in candidates:
        num = p.get("patent_number", "")
        s = scores.get(num, {})
        p["score"] = s.get("score", 1)
        p["reason"] = s.get("reason", "")
        p["mapped_questions"] = s.get("mapped_questions", [])

    print(f"[step7] {'分':>2}  {'专利号':<16}  {'映射子问题':<12}  标题 / 理由", flush=True)
    print(f"[step7] {'─'*80}", flush=True)
    for p in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
        qs = ",".join(p.get("mapped_questions", [])) or "-"
        reason = p.get("reason", "")[:35]
        print(f"[step7] {p.get('score',0):>2}  {p.get('patent_number',''):16s}  {qs:<12}  "
              f"{p.get('title','')[:30]}  {reason}", flush=True)
    return candidates


async def run(ctx: PipelineContext) -> None:
    t = cfg(ctx.tier)
    max_dl = t["patent_max"]
    max_retry = t["patent_retries"]

    kws = await _gap_keywords(ctx)
    chunks = _split_keywords(kws)
    print(f"\n[step7] ════════════════════════════════════════════════════════", flush=True)
    print(f"[step7] START  tier={ctx.tier}  max_dl={max_dl}  max_retry={max_retry}", flush=True)
    print(f"[step7] 关键词: {kws}", flush=True)
    print(f"[step7] ════════════════════════════════════════════════════════", flush=True)
    step_t0 = time.perf_counter()

    for attempt in range(max_retry + 1):
        ctx.retry_counters["patent"] = attempt
        attempt_t0 = time.perf_counter()
        print(f"\n[step7] ── 第 {attempt+1}/{max_retry+1} 轮 ──────────────────────────────────", flush=True)

        candidates = await _search_all_chunks(chunks, max_dl * 2, cdp_port=ctx.cdp_port)
        ctx.patent_candidates = candidates

        if not candidates:
            print(f"[step7] attempt {attempt}: no candidates, stop", flush=True)
            break

        candidates = await _score_patents(candidates, ctx)
        ctx.patent_candidates = candidates

        for p in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
            print(f"[step7] score={p.get('score',0)} {p.get('patent_number','')} {p.get('title','')[:50]}", flush=True)

        selected = [p.get("patent_number", "") for p in candidates if p.get("score", 0) >= 3][:max_dl]
        print(f"\n[step7] ── 下载阶段 ──────────────────────────────────────────", flush=True)
        print(f"[step7] 评分 ≥3 选中 {len(selected)} 篇: {selected}", flush=True)
        if not selected:
            print(f"[step7] 无专利评分 ≥3，停止", flush=True)
            break

        staging_pat = str(Path(ctx.staging_dir) / "patent") if ctx.staging_dir else ""
        if staging_pat:
            Path(staging_pat).mkdir(parents=True, exist_ok=True)

        convert_result: dict = {}
        t_dl = time.perf_counter()
        try:
            await cad_tools.patent_download(selected, staging_pat or ".", cdp_port=ctx.cdp_port)
            print(f"[step7] PDF 下载完成  耗时={time.perf_counter()-t_dl:.1f}s", flush=True)
            t_cv = time.perf_counter()
            convert_result = await cad_tools.patent_convert(staging_pat or ".")
            cv = {k: convert_result.get(k) for k in ('ok', 'skip', 'fail')}
            print(f"[step7] PDF→MD 转换完成  耗时={time.perf_counter()-t_cv:.1f}s  {cv}", flush=True)
        except Exception as exc:
            print(f"[step7] 下载/转换出错 耗时={time.perf_counter()-t_dl:.1f}s: {type(exc).__name__}: {exc}", flush=True)

        # 把新 MD 目录注册为 PendingDocument（待管理员审批入库）
        # 富化：补全标题/摘要/映射子问题（下载结果只有专利号；无 MD 时也能作纯文本引用）
        cand_by_num = {c.get("patent_number"): c for c in candidates if c.get("patent_number")}
        downloaded = []
        for n in selected:
            meta = cand_by_num.get(n, {})
            downloaded.append({
                "patent_number": n,
                "filename": f"{n}.md",
                "title": meta.get("title", ""),
                "abstract": meta.get("abstract", ""),
                "mapped_questions": meta.get("mapped_questions", []),
            })
        # 按专利号去重：重试轮次/step8 回跳可能重复选中同一专利，
        # 累积重复会导致 PendingDocument 重复注册（审核列表里同一专利出现多次）
        seen_nums = {p.get("patent_number") for p in ctx.patent_downloaded}
        fresh = [d for d in downloaded if d["patent_number"] not in seen_nums]
        ctx.patent_downloaded.extend(fresh)
        _update_panorama(ctx, fresh, source_type="patent")

        # 检查缺口（专利按 ⚠️ 也算覆盖，不强求 ✅）
        def _pat_gap_open(g: dict) -> bool:
            direction = g.get("direction", "")
            for row in ctx.panorama_table:
                if row.direction == direction and row.coverage in ("✅", "⚠️"):
                    return False
            return True

        uncovered = [g for g in ctx.gaps if _pat_gap_open(g)]
        print(f"\n[step7] 第 {attempt+1} 轮小结: 耗时={time.perf_counter()-attempt_t0:.1f}s  "
              f"新入库={len(fresh)}  未覆盖缺口={len(uncovered)}/{len(ctx.gaps)}", flush=True)
        if not uncovered:
            print(f"[step7] 全部缺口已覆盖，停止", flush=True)
            break

        if not fresh:
            print(f"[step7] 本轮无新专利，停止重试", flush=True)
            break

        if attempt < max_retry:
            kws = [g.get("keywords", [kws[0]])[0] for g in uncovered[:3]]
            chunks = _split_keywords(kws)
            print(f"[step7] 换词重试: {kws}", flush=True)

    print(f"\n[step7] ════════════════════════════════════════════════════════", flush=True)
    print(f"[step7] END  总耗时={time.perf_counter()-step_t0:.1f}s  "
          f"共 {ctx.retry_counters.get('patent',0)+1} 轮  累计入库={len(ctx.patent_downloaded)} 篇", flush=True)
    print(f"[step7] ════════════════════════════════════════════════════════", flush=True)
