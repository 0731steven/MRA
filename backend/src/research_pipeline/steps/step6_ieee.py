"""Step 6 — IEEE 两段式检索（R5 两段式唯一路径，R8 验货）。

流程：
  两轮搜索（宽泛 + 窄限定词）→ 合并去重 → LLM 评分（含 Override）
  → 下载选中 DOI → ingest_pdf 转换 → 增量更新全景表

R8 Override 规则：
  - 唯一解（该 DOI 是某子问题唯一直接回答且本地无覆盖）→ 忽略分数纳入
  - 发表 <2 年 top 1 → 忽略分数纳入
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ..context import PipelineContext, PanoramaRow
from ..tier import cfg
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))


def _resolve_ieee_md(ctx: PipelineContext, ident: str) -> tuple[str, str]:
    """按裸 id 子串定位 IEEE MD（MinerU/paper_manager 命名 0_Others_<id>_<id>.md）。

    下载脚本只回传 {"doi": id}，而落地 MD 文件名带分类前缀，精确名匹配不到。
    返回 (绝对路径, 文件名)，找不到返回 ("", "")。
    """
    if not ident:
        return "", ""
    bases: list[Path] = []
    if ctx.staging_dir:
        bases.append(Path(ctx.staging_dir))
    bases.append(WILSON_LIB / "ieee_paper_md")
    for base in bases:
        if base.exists():
            hits = list(base.rglob(f"*{ident}*.md"))
            if hits:
                return str(hits[0]), hits[0].name
    return "", ""


def _enrich_new_papers(ctx: PipelineContext, new_papers: list[dict], scored: list[dict]) -> list[dict]:
    """用候选元数据（标题/摘要/年份/评分）+ 真实 MD 路径富化下载结果。

    ieee_download 只回传 [{"doi": id}]，缺标题/摘要/路径会导致 step9 把这些论文
    整体丢弃（空 stem）或当作"无正文"。这里补全，使其成为可直接引用的素材。
    """
    cand_by_doi = {c.get("doi"): c for c in scored if c.get("doi")}
    enriched: list[dict] = []
    for np in new_papers:
        doi = np.get("doi", "")
        meta = cand_by_doi.get(doi, {})
        md_path, md_name = _resolve_ieee_md(ctx, doi)
        enriched.append({
            "doi": doi,
            "title": np.get("title") or meta.get("title", ""),
            "abstract": meta.get("abstract", ""),
            "year": meta.get("year"),
            "score": meta.get("score"),
            "mapped_questions": meta.get("mapped_questions", []),
            "path": md_path,
            "filename": md_name,
        })
    return enriched

_SCORE_SYSTEM = """你是 IC 设计领域的研究助手。

评估以下 IEEE 论文候选与子问题的相关性（1-5 分）。

评分标准：
5 — 直接回答某子问题，是不可或缺的一手资料
4 — 高度相关，有直接参考价值
3 — 部分相关，可作为背景参考
2 — 相关性低，仅泛泛提及
1 — 不相关

Override 规则（忽略分数直接纳入，在 override 字段注明原因）：
- 唯一解：该论文是某子问题的唯一直接回答，本地无覆盖 → override="unique"
- 新论文：发表 ≤2 年，在候选中排名第 1 → override="recent_top1"

输出 JSON（不加 markdown 代码块）：
{
  "scores": [
    {
      "doi": "10.xxxx/xxx",
      "score": 4,
      "reason": "直接分析 LDO PSRR 补偿电路",
      "mapped_questions": ["Q1", "Q2"],
      "override": ""
    }
  ]
}"""


_GAP_KW_SYSTEM = """你是 IC 设计领域文献检索专家。

根据用户给出的「待补搜缺口列表」，提炼出最适合在 IEEE Xplore 搜索的关键词列表。

要求：
- 输出 5~8 个独立的搜索短语，每个 2~5 个英文单词
- 每个短语单独搜索时能在 IEEE 返回有效结果（不要太泛也不要太长）
- 优先覆盖「核心」类缺口，「约束」类次之，「邻域」类可省略
- 不同缺口尽量用不同短语，避免重复

输出 JSON（不加 markdown 代码块）：
{"queries": ["low power SAR ADC", "delta-sigma modulator design", ...]}"""


async def _gap_keywords(ctx: PipelineContext) -> list[str]:
    """用 LLM 从缺口列表提炼精简的 IEEE 搜索关键词。"""
    if not ctx.gaps:
        return ctx.keywords

    gaps_text = "\n".join(
        f"- [{g.get('category','核心')}] {g.get('direction', '')}：{', '.join(g.get('keywords', []))}"
        for g in ctx.gaps
    )
    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"待补搜缺口：\n{gaps_text}"
    )
    llm = LLMClient(step=6)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_GAP_KW_SYSTEM,
            max_tokens=512,
        )
        queries = [q.strip() for q in result.get("queries", []) if q.strip()]
        if queries:
            print(f"[step6] LLM gap keywords: {queries}", flush=True)
            return queries
    except Exception as exc:
        print(f"[step6] gap keyword LLM failed, fallback: {exc}", flush=True)

    # fallback：直接截断原始 keywords
    seen: set[str] = set()
    result_list: list[str] = []
    for gap in ctx.gaps:
        for kw in gap.get("keywords", []):
            k = " ".join(kw.strip().split()[:4])
            if k and k not in seen:
                seen.add(k)
                result_list.append(k)
    return result_list or ctx.keywords


async def _search_and_merge(keywords: list[str], max_results: int, cdp_port: int | None = None) -> list[dict]:
    """每个关键词单独搜索，结果合并去重。

    ieee_search.py 把所有 argv 用 " ".join 拼成一个查询串，多个关键词拼在一起会导致
    IEEE API 返回 0 结果，所以每个关键词必须单独调用一次。
    每个关键词截到 ≤4 词，最多取前 5 个关键词搜索（避免请求过多）。
    """
    def _cap(kw: str, max_words: int = 4) -> str:
        return " ".join(kw.strip().split()[:max_words])

    seen_dois: dict[str, dict] = {}
    t0 = time.perf_counter()

    queries = [_cap(k) for k in keywords[:5] if k.strip()]
    print(f"[step6] search queries={queries} max={max_results}", flush=True)

    for i, q in enumerate(queries):
        try:
            r = await cad_tools.ieee_search_candidates([q], max_results, cdp_port=cdp_port)
            n = 0
            for p in r.get("papers", r.get("results", [])):
                doi = p.get("doi", "")
                if doi and doi not in seen_dois:
                    seen_dois[doi] = p
                    n += 1
            print(f"[step6] query[{i}] '{q}' hits={n}", flush=True)
        except Exception as exc:
            print(f"[step6] query[{i}] '{q}' error: {type(exc).__name__}: {exc}", flush=True)

    print(f"[step6] search merged={len(seen_dois)} total {time.perf_counter()-t0:.1f}s", flush=True)
    return list(seen_dois.values())


async def _score_candidates(candidates: list[dict], ctx: PipelineContext) -> list[dict]:
    """LLM 评分候选列表，返回含 score / override 的候选。"""
    if not candidates:
        return []

    # 分组截断：新论文（≤2 年）最多取 5 篇，高引用旧论文补齐至 20 篇
    # 防止低引用但高相关的新论文在按 cited_by 排序时被截掉
    current_year = datetime.now(timezone.utc).year
    new_papers_pool = [p for p in candidates if (current_year - int(p.get("year") or 0)) <= 2]
    old_papers_pool = [p for p in candidates if p not in new_papers_pool]

    new_slot = sorted(new_papers_pool, key=lambda p: p.get("cited_by", 0), reverse=True)[:5]
    remaining = 20 - len(new_slot)
    old_slot = sorted(old_papers_pool, key=lambda p: p.get("cited_by", 0), reverse=True)[:remaining]

    to_score = new_slot + old_slot
    scored_set = set(id(p) for p in to_score)
    unscored = [p for p in candidates if id(p) not in scored_set]

    sub_q_text = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    candidate_text = json.dumps(
        [{"doi": p.get("doi"), "title": p.get("title"), "year": p.get("year"), "abstract": p.get("abstract", "")[:300]}
         for p in to_score],
        ensure_ascii=False,
    )
    user_msg = (
        f"用户问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题：\n{sub_q_text}\n\n"
        f"候选论文（JSON）：\n{candidate_text}"
    )

    llm = LLMClient(step=6)
    t0 = time.perf_counter()
    print(f"[step6] scoring {len(to_score)} candidates via LLM...", flush=True)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_SCORE_SYSTEM,
            max_tokens=2048,
        )
        scores = {s["doi"]: s for s in result.get("scores", [])}
        print(f"[step6] scoring done: {len(scores)} scores in {time.perf_counter()-t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"[step6] LLM scoring error after {time.perf_counter()-t0:.1f}s: {type(exc).__name__}: {exc}", flush=True)
        scores = {}

    # Merge scores back into candidates
    for p in to_score:
        doi = p.get("doi", "")
        s = scores.get(doi, {})
        p["score"] = s.get("score", 1)
        p["override"] = s.get("override", "")
        p["mapped_questions"] = s.get("mapped_questions", [])

    # Unscored candidates default to score=1 (won't be downloaded)
    for p in unscored:
        p["score"] = 1
        p["override"] = ""
        p["mapped_questions"] = []

    return to_score + unscored


def _select_dois(candidates: list[dict], max_results: int) -> list[str]:
    """按评分选择下载 DOI，含 Override 规则。"""
    selected: list[str] = []
    for p in candidates:
        doi = p.get("doi", "")
        if not doi:
            continue
        if p.get("override"):
            selected.append(doi)
        elif p.get("score", 0) >= 3:
            selected.append(doi)
    # 按分数排序，取前 max
    scored = [(p.get("score", 0), p.get("doi", "")) for p in candidates if p.get("doi") in selected]
    scored.sort(reverse=True)
    return [doi for _, doi in scored[:max_results]]


async def run(ctx: PipelineContext) -> None:
    t = cfg(ctx.tier)
    max_dl = t["ieee_max"]
    max_retry = t["ieee_retries"]

    kws = await _gap_keywords(ctx)
    print(f"[step6] START tier={ctx.tier} max_dl={max_dl} max_retry={max_retry} keywords={kws}", flush=True)
    step_t0 = time.perf_counter()

    for attempt in range(max_retry + 1):
        ctx.retry_counters["ieee"] = attempt
        attempt_t0 = time.perf_counter()
        print(f"[step6] === attempt {attempt}/{max_retry} === keywords={kws}", flush=True)

        # 搜索 + 合并
        candidates = await _search_and_merge(kws, max_dl * 2, cdp_port=ctx.cdp_port)
        ctx.ieee_candidates = candidates

        if not candidates:
            print(f"[step6] attempt {attempt}: no candidates, stop", flush=True)
            break

        # LLM 评分
        candidates = await _score_candidates(candidates, ctx)
        ctx.ieee_candidates = candidates

        # 选 DOI
        dois = _select_dois(candidates, max_dl)
        print(f"[step6] attempt {attempt}: selected {len(dois)} DOIs to download", flush=True)
        if not dois:
            print(f"[step6] attempt {attempt}: no DOI scored >=3, stop", flush=True)
            break

        # 下载
        staging_ieee = str(Path(ctx.staging_dir) / "ieee") if ctx.staging_dir else ""
        if staging_ieee:
            Path(staging_ieee).mkdir(parents=True, exist_ok=True)
        t_dl = time.perf_counter()
        try:
            dl_result = await cad_tools.ieee_download(dois, staging_ieee or ".", cdp_port=ctx.cdp_port)
            new_papers = dl_result.get("new_papers", dl_result.get("papers", []))
            print(f"[step6] download {len(new_papers)} papers in {time.perf_counter()-t_dl:.1f}s", flush=True)
        except Exception as exc:
            print(f"[step6] ieee_download error after {time.perf_counter()-t_dl:.1f}s: {type(exc).__name__}: {exc}", flush=True)
            new_papers = []

        # PDF → MD
        if staging_ieee:
            t_ing = time.perf_counter()
            try:
                await cad_tools.ingest_pdf(staging_ieee)
                print(f"[step6] ingest_pdf done in {time.perf_counter()-t_ing:.1f}s", flush=True)
            except Exception as exc:
                print(f"[step6] ingest_pdf error after {time.perf_counter()-t_ing:.1f}s: {type(exc).__name__}: {exc}", flush=True)

        # 富化：补全标题/摘要/年份 + 解析真实 MD 路径（转换落地后再解析才能命中）
        new_papers = _enrich_new_papers(ctx, new_papers, candidates)
        n_resolved = sum(1 for p in new_papers if p.get("path"))
        print(f"[step6] downloaded={len(new_papers)} md_resolved={n_resolved}", flush=True)

        # 按 DOI（退化到 path/title）去重：重试轮次/step8 回跳可能重复选中同一篇，
        # 累积重复会导致 PendingDocument 重复注册（审核列表里同一论文出现多次）
        def _pkey(p: dict) -> str:
            return p.get("doi") or p.get("path") or p.get("title") or ""
        seen_keys = {_pkey(p) for p in ctx.ieee_new_papers}
        fresh = [p for p in new_papers if _pkey(p) not in seen_keys]

        ctx.ieee_downloaded.extend(fresh)
        ctx.ieee_new_papers.extend(fresh)

        # R8：验货 — 逐篇确认与子问题相关
        for p in fresh:
            mapped = p.get("mapped_questions") or [q.id for q in ctx.sub_questions[:1]]
            p["mapped_questions"] = mapped

        # 增量更新全景表
        _update_panorama(ctx, fresh, source_type="ieee")

        # 检查缺口是否消除
        uncovered = [g for g in ctx.gaps if _gap_still_open(ctx, g)]
        print(f"[step6] attempt {attempt} done in {time.perf_counter()-attempt_t0:.1f}s "
              f"| fresh={len(fresh)} uncovered_gaps={len(uncovered)}/{len(ctx.gaps)}", flush=True)
        if not uncovered:
            print(f"[step6] all gaps closed, stop", flush=True)
            break

        # fresh=0 说明候选已穷尽，再重试相同关键词无意义
        if fresh == 0:
            print(f"[step6] fresh=0, no new papers this round, stop retrying", flush=True)
            break

        # 换词重试
        if attempt < max_retry:
            kws = [g.get("keywords", [kws[0]])[0] for g in uncovered[:3]]
            print(f"[step6] retry with new keywords={kws}", flush=True)

    print(f"[step6] END total={time.perf_counter()-step_t0:.1f}s "
          f"attempts={ctx.retry_counters.get('ieee',0)+1} downloaded={len(ctx.ieee_new_papers)}", flush=True)


def _gap_still_open(ctx: PipelineContext, gap: dict) -> bool:
    direction = gap.get("direction", "")
    for row in ctx.panorama_table:
        if row.direction == direction and row.coverage == "✅":
            return False
    return True


def _update_panorama(ctx: PipelineContext, new_papers: list[dict], source_type: str) -> None:
    """增量更新全景表（新增行 / 刷新覆盖状态）。"""
    existing_dirs = {r.direction for r in ctx.panorama_table}
    for p in new_papers:
        fname = p.get("filename", p.get("title", ""))
        # 简单策略：将 mapped_questions 对应的缺口方向标为 ✅
        for gap in ctx.gaps:
            direction = gap.get("direction", "")
            if direction in existing_dirs:
                for row in ctx.panorama_table:
                    if row.direction == direction:
                        row.coverage = "✅" if source_type == "ieee" else "⚠️"
                        if fname and fname not in row.covering_papers:
                            row.covering_papers.append(fname)
            else:
                # 新增行
                ctx.panorama_table.append(PanoramaRow(
                    direction=direction,
                    category=gap.get("category", "核心"),
                    mentioned_sources=[fname] if fname else [],
                    coverage="✅" if source_type == "ieee" else "⚠️",
                    covering_papers=[fname] if fname else [],
                ))
                existing_dirs.add(direction)
