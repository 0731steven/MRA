"""Step 3 — 本地搜索（两轮：宽泛 + 窄限定词）+ 覆盖初评。

两轮搜索按路径去重合并，检查已有报告是否完全覆盖当前问题。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..context import PipelineContext
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

_COVERAGE_SYSTEM = """你是 IC 设计领域的研究助手。

对一份"已有研究报告"做两项判断，同时输出：

1. **覆盖（covers）**：报告主题与当前问题一致，且每个子问题都能找到实质性回答。
   判定从严：不同器件/技术对象（如问 GaN 栅驱、报告写带隙基准）即使共享个别术语也判为不覆盖。

2. **完整（complete）**：报告结构完整，没有明显截断、缺失章节或生成中断迹象。
   以下任一情况判为不完整：
   - 报告在句子或段落中间突然结束
   - 缺少"参考文献"或"结论"等应有章节

输出 JSON（不加 markdown 代码块）：
{"covers": true/false, "complete": true/false, "reason": "一句话说明"}"""


async def _report_covers_question(ctx: PipelineContext, report_path: str) -> bool:
    """LLM 判断已有报告是否完全覆盖当前问题且内容完整。

    两项都满足才走快捷路径：覆盖（主题一致+子问题有实质回答）+ 完整（无截断/缺章节）。
    任一不满足则重新跑完整流水线。
    """
    try:
        full = Path(report_path).read_text(encoding="utf-8", errors="ignore")
        # 取首尾各 2000 字，让 LLM 既能看到摘要/全景表，又能判断结尾是否完整
        content = full[:2000] + ("\n...\n" + full[-2000:] if len(full) > 4000 else full[2000:])
    except Exception:
        return False
    if not content.strip():
        return False
    sub_q = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    user_msg = (
        f"当前问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题：\n{sub_q}\n\n"
        f"已有报告（首尾各 2000 字）：\n{content}"
    )
    llm = LLMClient(step=5)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_COVERAGE_SYSTEM,
            max_tokens=4096,
        )
        covers = bool(result.get("covers"))
        complete = bool(result.get("complete"))
        reason = result.get("reason", "")
        print(f"[step3] report check: covers={covers} complete={complete} — {reason}", flush=True)
        return covers and complete
    except Exception as exc:
        print(f"[step3] coverage check failed, treating as not-covered: {exc}", flush=True)
        return False


_RELEVANCE_SYSTEM = """你是 IC 设计领域的研究助手。

本地搜索按关键词**子串匹配**召回文献，可能混入主题不相关的结果（例如查"GaN 栅极驱动"
却因正文出现 "level shifter" 而召回 LDO 论文）。请逐篇判断候选与当前问题/子问题是否**主题相关**
（研究对象一致或直接相关才算相关；仅因个别通用词偶然命中、研究对象不同的，判为不相关）。

输出 JSON（不加 markdown 代码块），只列出**主题相关**的候选编号：
{"relevant_indices": [0, 2, 5]}"""


def _candidate_digest(c: dict) -> str:
    """读候选文献正文开头作摘要（MinerU frontmatter 多为垃圾，跳过读正文取真实标题/摘要）。"""
    path = c.get("path", "")
    if not path:
        return c.get("title", "")
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return c.get("title", "")
    body = raw
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end > 0:
            body = raw[end + 3:]
    return " ".join(body.split())[:300]


async def _filter_relevant_candidates(ctx: PipelineContext, candidates: list[dict]) -> list[dict]:
    """LLM 语义过滤本地候选，剔除 grep 子串匹配误召回的不相关文献（R6 语义判断）。

    只过滤 paper/patent；report/survey/concept 原样保留（report 另由覆盖校验处理）。
    LLM 调用异常 → 保守保留全部（不因瞬时错误丢素材）；LLM 正常返回空 → 按其判定全部剔除。
    """
    core = [c for c in candidates if c.get("type") in ("paper", "patent")]
    others = [c for c in candidates if c.get("type") not in ("paper", "patent")]
    if len(core) <= 1:
        return candidates
        return candidates  # 0/1 篇无需过滤

    digests = "\n\n".join(f"[{i}] {_candidate_digest(c)}" for i, c in enumerate(core))
    sub_q = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    user_msg = (
        f"当前问题：{ctx.clarified_text or ' '.join(ctx.keywords)}\n\n"
        f"子问题：\n{sub_q}\n\n"
        f"候选文献（共 {len(core)} 篇）：\n{digests}"
    )
    llm = LLMClient(step=5)  # 复用 step5 轻量模型
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_RELEVANCE_SYSTEM,
            max_tokens=4096,
        )
    except Exception as exc:
        print(f"[step3] relevance filter failed, keeping all {len(core)}: {exc}", flush=True)
        return candidates

    keep = {i for i in result.get("relevant_indices", []) if isinstance(i, int)}
    filtered = [c for i, c in enumerate(core) if i in keep]
    print(f"[step3] relevance filter: kept {len(filtered)}/{len(core)} papers/patents", flush=True)
    return filtered + others


def _parse_local_search_result(r: dict) -> dict[str, dict]:
    """local_search.py 输出 {papers:[path,...], patents:[path,...], reports:[path,...]}
    转换为 {path: {path, type, title}} 供 pipeline 使用。
    """
    from pathlib import Path as _Path
    items: dict[str, dict] = {}
    for path in r.get("papers", []):
        if path:
            items[path] = {"path": path, "type": "paper",
                           "title": _Path(path).stem, "filename": _Path(path).name}
    for path in r.get("patents", []):
        if path:
            items[path] = {"path": path, "type": "patent",
                           "title": _Path(path).stem, "filename": _Path(path).name}
    for path in r.get("surveys", []):
        if path:
            items[path] = {"path": path, "type": "survey",
                           "title": _Path(path).stem, "filename": _Path(path).name}
    for path in r.get("reports", []):
        if path:
            items[path] = {"path": path, "type": "report",
                           "title": _Path(path).stem, "filename": _Path(path).name}
    for path in r.get("concepts", []):
        if path:
            items[path] = {"path": path, "type": "concept",
                           "title": _Path(path).stem, "filename": _Path(path).name}
    return items


async def run(ctx: PipelineContext) -> None:
    keywords = ctx.keywords
    # 轮 2：窄限定词（取最具体的前 2 个关键词；不加 "circuit"/"design" 等泛词——
    # 它们几乎命中 vault 内每篇论文/报告，会把无关文献和报告误召回）
    narrow = keywords[:2]

    async def _search(kws: list[str]) -> dict[str, dict]:
        try:
            r = await cad_tools.local_search(kws)
            return _parse_local_search_result(r)
        except Exception:
            return {}

    r1_items, r2_items = await asyncio.gather(_search(keywords), _search(narrow))

    all_candidates: dict[str, dict] = {**r1_items, **r2_items}
    candidates = list(all_candidates.values())

    # LLM 语义过滤：剔除 grep 子串匹配误召回的不相关文献（如查 GaN 误召回 LDO 论文）。
    # 早在 step3 过滤，连带让 step4 全景表不被无关论文污染。
    candidates = await _filter_relevant_candidates(ctx, candidates)
    ctx.local_candidates = candidates

    # 有已有报告且**完全覆盖**才走快捷路径（R: reports 非空且完全覆盖 → 跳 Step 10）。
    # 必须 LLM 校验覆盖，否则泛词误命中的不相关报告会劫持流水线（如 GaN 提问回带隙报告）。
    reports = [c for c in candidates if c.get("type") == "report"]
    for rep in reports:
        if await _report_covers_question(ctx, rep.get("path", "")):
            ctx.existing_report_path = rep.get("path")
            break

    # 判断是否有核心素材（用于决定是否立即建全景表）
    core = [c for c in candidates if c.get("type") in ("paper", "patent")]
    ctx.has_core_materials = len(core) > 0

    # 初评覆盖（所有子问题先标 ⚠️，留给 Step 5 LLM 精评）
    ctx.initial_coverage = {q.id: "⚠️" for q in ctx.sub_questions}
    if not candidates:
        ctx.initial_coverage = {q.id: "❌" for q in ctx.sub_questions}
