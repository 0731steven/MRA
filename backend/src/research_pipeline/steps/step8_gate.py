"""Step 8 — 两阶段阅读 + Gate 1/2/3 校验。

阶段 1：读 title+abstract+frontmatter → 按子问题贡献打分（1-5）
阶段 2：排除 ≤2 分 → 取前 N 篇并行全文读 + 补 frontmatter
Gate 1: check_report.py --papers <staging_dir>
Gate 2: check_report.py --lint-papers <staging_dir>
Gate 3: check_report.py --lint-patents
bounce_needed = True 当 Gate 1 失败且存在某子问题唯一覆盖被移出
"""
from __future__ import annotations
import asyncio
import os
from pathlib import Path

from ..context import PipelineContext
from ..tier import cfg
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

_PHASE1_SYSTEM = """你是 IC 设计领域的研究助手。

快速阅读论文摘要和 frontmatter，按对子问题的贡献度打分（1-5）。

评分标准：
5 — 直接回答该子问题的核心文献
4 — 有直接参考价值
3 — 部分相关
2 — 相关性弱
1 — 不相关

输出 JSON（不加 markdown 代码块）：
{
  "scores": [
    {"filename": "paper.md", "score": 4, "mapped_questions": ["Q1"]}
  ]
}"""

_PHASE2_SYSTEM = """你是 IC 设计领域的研究助手。

阅读论文全文，提取关键电路细节供报告撰写使用。

返回 JSON（不加 markdown 代码块）：
{
  "filename": "xxx.md",
  "frontmatter_updates": {
    "core_innovation": "核心创新点，一句话",
    "key_metrics": "关键指标，如 ENOB / FOM / 功耗数字"
  },
  "circuit_details": "电路细节的详细描述，包含电路原理、关键数字、与子问题的对应关系"
}

注意：
- 所有字段从论文正文提取，找不到的填空字符串 ""，不要编造
- circuit_details 尽量详细，报告 step9 会直接引用"""

WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))


def _collect_all_papers(ctx: PipelineContext) -> list[dict]:
    """合并本地候选 + 新下载论文 + 专利，优先新素材。"""
    seen: dict[str, dict] = {}
    # 本地已有
    for p in ctx.local_candidates:
        fname = p.get("filename", p.get("path", ""))
        if fname:
            seen[fname] = {**p, "is_new": False}
    # 新下载 IEEE 论文（覆盖同名）
    for p in ctx.ieee_new_papers:
        fname = p.get("filename", p.get("path", ""))
        if fname:
            seen[fname] = {**p, "is_new": True}
    # 新下载专利
    for p in ctx.patent_downloaded:
        fname = p.get("filename", p.get("patent_number", ""))
        if fname:
            seen[fname] = {**p, "is_new": True, "source": "patent"}
    return list(seen.values())


def _read_paper_summary(p: dict, ctx: PipelineContext) -> str:
    """读取论文/专利 title + abstract + frontmatter（前 2000 字符）。"""
    path = p.get("path", p.get("filename", ""))
    if not path:
        return ""
    try:
        # 先找 staging，再找 vault
        for base in ([Path(ctx.staging_dir)] if ctx.staging_dir else []) + [WILSON_LIB]:
            full = base / path if not Path(path).is_absolute() else Path(path)
            if full.exists():
                return full.read_text(encoding="utf-8", errors="ignore")[:2000]

        # 专利：filename 只有简单名如 CN113991981B.md，需要在 staging patent_md 下搜索
        patent_number = p.get("patent_number", "")
        if patent_number and ctx.staging_dir:
            patent_md_dir = Path(ctx.staging_dir) / "patent_md"
            if patent_md_dir.exists():
                for md in patent_md_dir.rglob("*.md"):
                    if patent_number in md.name:
                        return md.read_text(encoding="utf-8", errors="ignore")[:2000]
    except Exception:
        pass
    return ""


async def _phase1_score(papers: list[dict], ctx: PipelineContext) -> list[dict]:
    if not papers:
        return papers

    summaries = "\n\n---\n\n".join(
        f"### {p.get('filename', p.get('path', ''))}\n{_read_paper_summary(p, ctx)}"
        for p in papers
    )
    sub_q_text = "\n".join(f"{q.id}: {q.text}" for q in ctx.sub_questions)
    user_msg = f"子问题：\n{sub_q_text}\n\n论文摘要：\n{summaries}"

    llm = LLMClient(step=5)  # 复用 step5 轻量模型
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_PHASE1_SYSTEM,
            max_tokens=4096,
        )
        scores = {s["filename"]: s for s in result.get("scores", [])}
    except Exception:
        scores = {}

    for p in papers:
        fname = p.get("filename", p.get("path", ""))
        s = scores.get(fname, {})
        p["phase1_score"] = s.get("score", 2)
        p.setdefault("mapped_questions", s.get("mapped_questions", []))
    return papers


async def _phase2_read_one(p: dict, ctx: PipelineContext) -> dict:
    """全文读一篇，补 frontmatter。"""
    path = p.get("path", p.get("filename", ""))
    text = ""
    full_path_found = None
    for base in ([Path(ctx.staging_dir)] if ctx.staging_dir else []) + [WILSON_LIB]:
        full = base / path if not Path(path).is_absolute() else Path(path)
        if full.exists():
            text = full.read_text(encoding="utf-8", errors="ignore")[:8000]
            full_path_found = full
            break

    # 专利 fallback：用 patent_number 搜索
    if not text:
        patent_number = p.get("patent_number", "")
        if patent_number and ctx.staging_dir:
            patent_md_dir = Path(ctx.staging_dir) / "patent_md"
            if patent_md_dir.exists():
                for md in patent_md_dir.rglob("*.md"):
                    if patent_number in md.name:
                        text = md.read_text(encoding="utf-8", errors="ignore")[:8000]
                        full_path_found = md
                        break

    if not text:
        return p

    user_msg = f"论文内容：\n{text}"
    llm = LLMClient(step=9)
    try:
        result = await llm.chat_json(
            [ChatMessage(role="user", content=user_msg)],
            system=_PHASE2_SYSTEM,
            max_tokens=8192,
        )
        updates = result.get("frontmatter_updates", {})
        if updates and full_path_found:
            _patch_frontmatter(full_path_found, updates)
        p["circuit_details"] = result.get("circuit_details", "")
        p["frontmatter_updates"] = updates
    except Exception:
        pass
    return p


def _patch_frontmatter(path: Path, updates: dict) -> None:
    """将 updates 写入 MD 文件的 frontmatter。"""
    try:
        import yaml
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return
        end = content.find("---", 3)
        if end < 0:
            return
        fm_text = content[3:end]
        fm = yaml.safe_load(fm_text) or {}
        for k, v in updates.items():
            if v and not fm.get(k):
                fm[k] = v
        new_fm = yaml.dump(fm, allow_unicode=True, default_flow_style=False)
        path.write_text(f"---\n{new_fm}---{content[end + 3:]}", encoding="utf-8")
    except Exception:
        pass


async def run(ctx: PipelineContext) -> None:
    t = cfg(ctx.tier)
    read_max = t["read_max"]

    all_papers = _collect_all_papers(ctx)

    # 阶段 1：概要全读（打分）
    all_papers = await _phase1_score(all_papers, ctx)
    ctx.reading_scores = [
        {"filename": p.get("filename", ""), "score": p.get("phase1_score", 1), "mapped_questions": p.get("mapped_questions", [])}
        for p in all_papers
    ]

    # 阶段 2：全文并行读（排除 ≤2 分，取前 N）
    phase2 = sorted(
        [p for p in all_papers if p.get("phase1_score", 1) > 2],
        key=lambda x: (x.get("is_new", False), x.get("phase1_score", 0)),
        reverse=True,
    )[:read_max]

    if phase2:
        results = await asyncio.gather(*[_phase2_read_one(p, ctx) for p in phase2])
        # Build lookup by filename so we can write circuit_details back to the
        # original ctx lists — _collect_all_papers creates copies so the in-place
        # mutations inside _phase2_read_one never reach the originals.
        details_map: dict[str, str] = {}
        for r in results:
            fname = r.get("filename", r.get("path", ""))
            cd = r.get("circuit_details", "")
            if fname and cd:
                details_map[fname] = cd
            ctx.frontmatter_status[fname] = bool(r.get("frontmatter_updates"))
        for p in ctx.local_candidates + ctx.ieee_new_papers + ctx.patent_downloaded:
            fname = p.get("filename", p.get("path", ""))
            if fname in details_map:
                p["circuit_details"] = details_map[fname]

    # Gate 校验
    staging_ieee = str(Path(ctx.staging_dir) / "ieee") if ctx.staging_dir else ""
    gate_pass = True

    # Gate 1: papers frontmatter
    code1, out1 = await cad_tools.check_report(staging_ieee, "papers")
    ctx.gate_results["gate1_papers"] = {"exit_code": code1, "output": out1[:2000]}
    if code1 != 0:
        gate_pass = False

    # Gate 2: lint papers
    code2, out2 = await cad_tools.check_report("", "lint-papers")
    ctx.gate_results["gate2_papers_lint"] = {"exit_code": code2, "output": out2[:2000]}

    # Gate 3: lint patents
    code3, out3 = await cad_tools.check_report("", "lint-patents")
    ctx.gate_results["gate3_patents_lint"] = {"exit_code": code3, "output": out3[:2000]}

    # 决定是否需要回跳（Gate 1 失败且某子问题失去唯一覆盖）
    if not gate_pass:
        # 简单策略：如有子问题没有任何高分素材，标记 bounce_needed
        q_covered = set()
        for p in phase2:
            for qid in p.get("mapped_questions", []):
                q_covered.add(qid)
        uncovered_qs = [q.id for q in ctx.sub_questions if q.id not in q_covered]
        ctx.bounce_needed = bool(uncovered_qs)
    else:
        ctx.bounce_needed = False
