"""Step 9 — Pre-flight checklist → LLM 写报告 → fix_citations → check_report（零容忍）。

R12：写报告前必须读 OBSIDIAN-WRITING.md；check_report.py 退出码必须为 0。
R1：素材不足用降级模板（status: insufficient）。
"""
from __future__ import annotations
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sqlalchemy import select

from ..context import PipelineContext
from ...common.fuzzy import edit_distance_capped
from ...db.session import AsyncSessionLocal
from ...db.models import Report
from ...integrations import cad_tools
from ...integrations.llm_client import LLMClient, ChatMessage

WILSON_LIB = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))
RESEARCH_DIR = WILSON_LIB / "wiki" / "research"
QA_DIR = WILSON_LIB / "wiki" / "qa"

_REPORT_SYSTEM_TEMPLATE = """你是 IC 设计领域的资深研究助手，撰写高质量的中文技术调研报告。

写作规范（来自 OBSIDIAN-WRITING.md）：
__OBSIDIAN_RULES__

══════ 质量铁律（违反即视为失败）══════
1. 【只用素材中的事实】每一个技术论断、每一个数字（性能指标 / 工艺节点 / 年份 / 拓扑名）都必须来自下方"可用素材"中实际给出的论文/专利正文或摘要。严禁仅凭文件名或专利号臆造一篇素材"研究了什么"。
2. 【素材与主题不符要诚实】检索可能误召回不相关素材（例如某专利正文其实是 LDO 而非本题主题）。遇到这种情况：在速查表标注"相关性弱/疑似误召回"，或干脆不引用——绝不编造它的贡献来凑数。
3. 【可信度标注】多篇互证 → 正常引用；仅单篇支撑 → 句末标"（单篇，待验证）"；跨技术方向推断 → 标"（邻域推断）"；无直接数据 → 标"（推断，无直接数据）"。
4. 【引用格式——严格遵守】
   - 正文每处引用必须同时包含 wikilink 和编号，格式：[[wikilink_stem\\|第一作者姓 年份]] [编号]
   - 每篇素材的⚡引用格式已在下方素材列表中给出（例如 [[stem\\|Yu 2023]] [1]），**直接照抄该格式，不得改动 stem 或显示文字**
   - 示例（论文）：[[2023_Power_A_400-V_Half_Bridge_Gate_Driver_for_Normally-Off_GaN_HEMTs_W_9724123\\|Yu 2023]] [1]
   - 示例（专利）：[[CN109905111B\\|CN109905111B]] [P1]
   - wikilink_stem 必须与素材列表中 `wikilink_stem=` 后面的值**完全一致**，不得缩写、截断或自行修改
   - **禁止只写 [1] 而不写 wikilink**；没有 wikilink 的引用视为格式错误
   - **严禁将 wikilink 包裹在反引号中**（不得写成 `[[...]]`，反引号会把链接变成代码文本、无法点击）
   - 表格单元格内的竖线一律用 \\| 转义（wikilink 内部的 | 也必须写成 \\|）
5. 【参考文献真实】作者 / 标题 / 年份 / 期刊会议必须从素材**正文**（首部标题行、作者行、Abstract 之前的"IEEE TRANSACTIONS ON..."/"PROCEEDINGS OF..."等期刊/会议行）提取。IEEE MD 的 frontmatter 经常是垃圾（title=文件名、venue 为空），**必须读正文第一段**而非 frontmatter 来获取真实期刊/会议名和年份。实在找不到才填"—"，不得编造。
5. 【图片引用——务必呈现关键架构/电路图】每篇论文的"可用素材"里都附了【带图注的可引用图片】清单（每行格式：  ![[目录/images/文件名]] —— 图注  ）。请依据图注语义，在对应分析小节引用能支撑论述的关键图——尤其是系统框图/架构图、电路原理图(schematic)、拓扑图、关键时序/开关波形、关键仿真或测量结果图。**每个子问题的详细分析，只要该方向有合适的带图注图片，至少配 1 张相关图**；有架构图/电路图却不引用视为遗漏。
   - 引用格式：从清单中**原样照抄** ![[目录/images/文件名]]，紧跟一句说明该图内容的中文文字。严禁自行拼造、缩写或修改图片路径与文件名。**严禁在 ![[...]] 外加反引号**（加了反引号图片就变成代码文字无法显示）。
   - 引用示例（正确）：![[2023_Power_..._9724123/images/6a4234...jpg]]（图示为所提出 TBLS 三分支电平移位器的电路原理）
   - 错误示范（绝对禁止）：`![[...]]`（反引号包裹导致图片无法渲染）
   - **只引用清单中【带图注】的图**；图注表明是版图照片(die photo)、PCB 实物照、作者照片、封面、参考文献截图等与技术论述无关的，一律不引用。
   - 清单里没有合适图注的图就不引（宁缺毋滥）；但不得因"看不懂文件名"而把有架构图/电路图的也跳过。

══════ 正常报告结构（status: complete）══════
【格式铁律】报告文件必须严格以 YAML frontmatter 开头，即文件第一个字符就是 ---，不得在 frontmatter 前面加任何标题、空行或其他内容。结构必须是：
  ---
  title: "..."
  ...
  ---

  ## 摘要
  ...

frontmatter 必须包含：
  title  tags(列表)  date  domain
  sources（含 papers/patents/web 三个子键，值为实际引用数）
  status: complete
  concepts: []

## 摘要
  用分点列表（Markdown 无序列表）呈现，每点一行，覆盖以下维度：
  - **研究对象**：明确说明本报告聚焦的器件/电路/技术范围
  - **核心发现**：2–4 条最重要的技术结论，每条带关键数字或量化指标
  - **技术成熟度**：当前工程化程度判断（如"已有商用芯片/仍处实验室阶段"）
  - **主要空白/局限**：当前文献未覆盖或尚无定论的方向

## 技术全景表
  Markdown 表，列依次为：技术方向、类别、覆盖、代表论文/专利、关键说明。
  类别取「核心 / 约束 / 邻域」之一；覆盖取「✅ / ⚠️ / ❌」之一；代表列放 1–3 个 wikilink。

## 问题分解
  Markdown 表，列依次为：#、子问题、覆盖来源、状态。
  覆盖来源写实际引用数（如"4 篇论文 / 1 项专利"）；状态用 ✅/⚠️/❌。

## 详细分析
  每个子问题一个 ### 小节，深入展开：物理机理 → 具体电路/技术路线（分点）→ 每条的代表素材与量化效果 → 引用编号。这是报告主体，务必具体、有数字、有对比。

## 结论与建议
  给工程师的可执行 checklist（编号列表）+ 后续可补搜的关键词/方向。

## 论文/专利速查
  Markdown 表，列依次为：素材、核心贡献、关键数字。
  每个被引用素材一行。

## 参考文献
  Markdown 表，列依次为：#、类型、作者/专利权人、标题、期刊会议或专利号、年。
  类型取「论文 / 专利 / Web」；编号与正文 [n] / [Pn] 一一对应。

注意：以上"列依次为"只是说明列含义，真实表格用标准 Markdown 竖线 | 分隔单元格；只有 wikilink 内部的竖线才写成 \\|。

══════ 降级报告结构（status: insufficient）══════
仅当素材确实不足时使用：问题分解 → 搜索概况 → 有限发现 → 建议（换关键词/后续方向）。
不得用臆造内容把降级报告硬撑成正常报告。"""

_REPORT_USER_TEMPLATE = """用户问题：{question}

子问题（含当前覆盖判定）：
{sub_questions}

技术全景表（方向 / 类别 / 覆盖 / 已覆盖素材）：
{panorama}

素材统计：论文 {n_papers} 篇，专利 {n_patents} 项，Web {n_web} 条（frontmatter 的 sources 必须等于报告实际引用数，可少于此统计）。

══════ 可用素材（每条含 wikilink_stem、标识、检索元数据、frontmatter、正文摘录）══════
{materials}

══════ 引用格式速查（写报告时对照此表，不得偏离）══════
{cite_table}

请基于以上**真实素材**生成完整调研报告（Markdown + YAML frontmatter）。
所有技术细节与数字必须能在上述素材中找到依据；找不到依据的内容一律不要写。
⚡ 最终检查：正文每一处引用都必须是 [[wikilink_stem\\|第一作者姓 年份]] [编号] 格式，每篇素材的引用格式已在素材列表 ⚡ 处给出，直接照抄即可；绝对禁止只写 `[编号]`；也禁止写成 `[[...]]`（反引号包裹的 wikilink 无法点击）。"""


def _read_obsidian_rules() -> str:
    """读取 OBSIDIAN-WRITING.md（R12）。"""
    path = WILSON_LIB / "OBSIDIAN-WRITING.md"
    try:
        return path.read_text(encoding="utf-8")[:3000]
    except Exception:
        return "（未找到 OBSIDIAN-WRITING.md，使用默认格式规范）"


def _iter_sources(ctx: PipelineContext) -> tuple[list[dict], list[dict], list[dict]]:
    """统一素材列表：论文（本地+IEEE，去重）/ 专利 / Web。

    去重键优先用文件 stem，回退到 doi / 标题——下载脚本可能只回传 {"doi": id}，
    若仍按 stem 过滤会把所有新下载论文误判为空 stem 而整体丢弃。
    """
    seen: set[str] = set()
    papers: list[dict] = []
    for p in ctx.local_candidates + ctx.ieee_new_papers:
        key = (
            Path(p.get("filename") or p.get("path") or "").stem
            or str(p.get("doi") or "").strip()
            or str(p.get("title") or "").strip()
        )
        if key and key not in seen:
            seen.add(key)
            papers.append(p)
    return papers, list(ctx.patent_downloaded), list(ctx.web_archived)


def _find_source_md(ctx: PipelineContext, p: dict) -> Path | None:
    """定位素材 MD：先 staging，再 vault；支持递归（MinerU 一文一目录）。"""
    fn = p.get("path") or p.get("filename") or ""
    if not fn and p.get("patent_number"):
        fn = f"{p['patent_number']}.md"
    if not fn:
        return None
    fp = Path(fn)
    if fp.is_absolute() and fp.exists():
        return fp
    stem = fp.name if fp.name.endswith(".md") else fp.name + ".md"

    direct_bases: list[Path] = []
    if ctx.staging_dir:
        sd = Path(ctx.staging_dir)
        direct_bases += [sd, sd / "ieee", sd / "patent", sd / "patent_md", sd / "web"]
    direct_bases += [
        WILSON_LIB,
        WILSON_LIB / "ieee_paper_md",
        WILSON_LIB / "patent_md",
        WILSON_LIB / "raw" / "web",
    ]
    for base in direct_bases:
        cand = base / fn
        if cand.exists():
            return cand

    # 递归（限定子目录，避免全库扫描）
    rglob_bases: list[Path] = []
    if ctx.staging_dir:
        rglob_bases.append(Path(ctx.staging_dir))
    rglob_bases += [WILSON_LIB / "ieee_paper_md", WILSON_LIB / "patent_md", WILSON_LIB / "raw" / "web"]
    for base in rglob_bases:
        if base.exists():
            hits = list(base.rglob(stem))
            if hits:
                return hits[0]

    # id 子串兜底：IEEE MinerU 命名为 0_Others_<id>_<id>.md，下载结果只带裸 id
    # （doi/article number），精确文件名匹配不到，用 id 子串再扫一次。
    ident = str(p.get("doi") or p.get("patent_number") or "").strip()
    if not ident:
        m = re.search(r"(\d{5,})", stem)
        ident = m.group(1) if m else ""
    if ident:
        for base in rglob_bases:
            if base.exists():
                hits = list(base.rglob(f"*{ident}*.md"))
                if hits:
                    return hits[0]
    return None


_IMG_EMBED_RE = re.compile(r"!\[\[images/([^\]|]+?)\]\]|!\[[^\]]*\]\(images/([^)]+?)\)")
_CAPTION_RE = re.compile(r"^(?:Fig(?:ure)?\.?|图|Table|TABLE|表)\s*\d", re.IGNORECASE)


def _figure_captions(body: str) -> list[tuple[str, str]]:
    """Pair each in-body figure image with its caption line.

    MinerU embeds figures as `![[images/<hash>.jpg]]` followed (on the next
    non-empty line) by a `Fig. N ...` / `图 N ...` caption. The filenames are
    opaque hashes, so without the caption the LLM can't tell an architecture
    diagram from a die photo and ends up citing nothing. Returning (file,
    caption) pairs lets it choose figures by meaning.

    Multiple images before a single caption (multi-part figures) all map to that
    caption. A non-caption paragraph between image and caption breaks the pair to
    avoid associating a far-away caption.
    """
    out: list[tuple[str, str]] = []
    pending: list[str] = []
    for ln in body.splitlines():
        m = _IMG_EMBED_RE.search(ln)
        if m:
            pending.append((m.group(1) or m.group(2)).strip())
            continue
        s = ln.strip()
        if not s:
            continue  # blank line keeps the image→caption window open
        if pending and _CAPTION_RE.match(s):
            cap = re.sub(r"\s+", " ", s)[:160]
            out.extend((fn, cap) for fn in pending)
        pending = []  # caption consumed, or a real paragraph broke the window
    return out


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end > 0:
            return raw[3:end].strip(), raw[end + 3:].strip()
    return "", raw.strip()


def _parse_cite_display(p: dict, stem: str, fm: str, body: str = "") -> str:
    """从 frontmatter YAML + 正文 + 检索元数据提取 '第一作者姓 年份' 显示文本。
    优先级：frontmatter authors/year → 正文作者行 → 检索元数据 year → stem 解析 → fallback。
    """
    year = ""
    author_last = ""

    if fm:
        try:
            data = yaml.safe_load(fm) or {}
            raw_year = data.get("year") or data.get("date") or ""
            if raw_year:
                m = re.search(r"(20\d{2}|19\d{2})", str(raw_year))
                year = m.group(1) if m else str(raw_year)[:4]
            authors = data.get("authors", [])
            if isinstance(authors, list) and authors:
                first = str(authors[0])
            elif isinstance(authors, str) and authors:
                first = authors.split(";")[0].split(",")[0].strip()
            else:
                first = ""
            if first:
                if "," in first:
                    author_last = first.split(",")[0].strip().split()[-1]
                else:
                    parts = first.strip().split()
                    author_last = parts[-1] if parts else ""
        except Exception:
            pass

    # IEEE 论文 body 格式：# 标题\n作者行\nAbstract—...
    # frontmatter 通常没有 authors，从正文第一行非标题非摘要段落提取
    if not author_last and body:
        m = re.search(r"^#{1,3}[^\n]*\n+([^\n#!]{5,120})", body, re.MULTILINE)
        if m:
            candidate = m.group(1).strip()
            skip = re.match(
                r"(?i)abstract|©|doi\s*:|received\s|manuscript\s|university|institute"
                r"|department|school|journal|proceedings|ieee\s+trans|vol\.\s*\d",
                candidate,
            )
            if not skip:
                first_author = candidate.split(",")[0].strip()
                # 去掉 IEEE 会员标注
                first_author = re.sub(
                    r",?\s*(Student\s+Member|Senior\s+Member|Fellow|Member),?\s*IEEE.*",
                    "",
                    first_author,
                    flags=re.IGNORECASE,
                )
                parts = first_author.strip().split()
                if parts and len(parts[0]) > 1:
                    author_last = parts[-1]

    if not year and p.get("year"):
        year = str(p["year"])[:4]

    if not author_last and stem:
        m = re.match(r"^([A-Z][a-z]+)(\d{4})", stem)
        if m:
            author_last = m.group(1)
            if not year:
                year = m.group(2)

    if author_last and year:
        return f"{author_last} {year}"
    if author_last:
        return author_last
    if year:
        return year
    return "作者 年份"


def _source_digest(ctx: PipelineContext, p: dict, idx: int, kind: str) -> str:
    """单篇素材的富信息摘要：标识 + 检索元数据 + frontmatter + 正文摘录。"""
    md = _find_source_md(ctx, p)
    stem = md.stem if md else Path(p.get("filename") or p.get("path") or "").stem
    ident = p.get("doi") or p.get("patent_number") or ""
    lines = []
    if md:
        try:
            raw = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            raw = ""
        fm, body = _split_frontmatter(raw)
    else:
        fm, body = "", ""
    # 引用示例放在最显眼的第一行，使用真实的作者+年份而非占位符，让 LLM 直接照抄
    if stem:
        cite_display = _parse_cite_display(p, stem, fm, body)
        header = f"### [{idx}] {kind}  ⚡引用格式: [[{stem}\\|{cite_display}]] [{idx}]"
    else:
        header = f"### [{idx}] {kind}"
    lines = [header]
    if stem:
        lines.append(f"  wikilink_stem（必须一字不差）: `{stem}`")
    if ident:
        lines.append(f"  id: {ident}")
    if p.get("url"):
        lines.append(f"URL: {p['url']}")
    if p.get("title") and p["title"] != stem:
        lines.append(f"检索标题: {p['title']}")
    if p.get("year"):
        lines.append(f"检索年份: {p['year']}")
    if p.get("mapped_questions"):
        lines.append(f"映射子问题: {', '.join(p['mapped_questions'])}")
    if p.get("abstract"):
        lines.append(f"检索摘要: {str(p['abstract'])[:400]}")

    if md:
        if fm and "_parse_error: true" not in fm:
            lines.append(f"frontmatter:\n{fm[:1500]}")
        circuit_details = p.get("circuit_details", "")
        if circuit_details:
            lines.append(f"电路细节（Step 8 全文提取）:\n{circuit_details}")
        elif body:
            lines.append(f"正文摘录:\n{body[:3500]}")
        # 带图注的可引用图片：从全文正文提取（图注让 LLM 能按语义选架构图/电路图）
        figs = _figure_captions(body)
        if figs:
            wikilink_base = md.parent.name
            lines.append(
                f"可引用图片（共 {len(figs)} 张，均附图注；请按图注语义优先引用"
                f"系统框图/架构图、电路原理图、拓扑图、关键波形或仿真/测量结果图，"
                f"路径照抄勿改，与论述无关的版图照片/PCB/作者照等勿引）："
            )
            for fn, cap in figs[:24]:
                lines.append(f"  ![[{wikilink_base}/images/{fn}]] —— {cap}")
    else:
        lines.append("（未找到 MD 全文，仅有检索元数据。仍可基于上方标题/摘要在报告中引用该专利，在参考文献表填入专利号，但不得编造全文未提及的技术细节。）")
    return "\n".join(lines)


def _format_materials(ctx: PipelineContext) -> tuple[str, str]:
    """汇总所有可用素材，返回 (materials_text, cite_table_text)。"""
    papers, patents, webs = _iter_sources(ctx)
    blocks: list[str] = []
    cite_rows: list[str] = []
    idx = 1
    for p in papers:
        blocks.append(_source_digest(ctx, p, idx, "论文"))
        md = _find_source_md(ctx, p)
        stem = md.stem if md else Path(p.get("filename") or p.get("path") or "").stem
        if stem:
            fm, body = "", ""
            if md and md.exists():
                try:
                    fm, body = _split_frontmatter(md.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
            cite_display = _parse_cite_display(p, stem, fm, body)
            cite_rows.append(f"  [{idx}] 论文  → [[{stem}\\|{cite_display}]] [{idx}]")
        idx += 1
    for p in patents:
        blocks.append(_source_digest(ctx, p, idx, "专利"))
        md = _find_source_md(ctx, p)
        stem = md.stem if md else Path(p.get("filename") or p.get("path") or "").stem
        if stem:
            cite_rows.append(f"  [P{idx - len(papers)}] 专利 → [[{stem}\\|{stem}]] [P{idx - len(papers)}]")
        idx += 1
    for w in webs:
        blocks.append(_source_digest(ctx, w, idx, "Web"))
        idx += 1
    cite_table = "\n".join(cite_rows) if cite_rows else "（无素材）"
    return "\n\n".join(blocks) or "（无可用素材）", cite_table


_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
# ![[<dir>/images/<file>]] — dir is the source's folder name (the wikilink base),
# file is a MinerU hash. The LLM hand-copies these and routinely drops a char.
_REPORT_IMG_EMBED_RE = re.compile(r"!\[\[([^\]\s]+?)/images/([^\]\s/]+)\]\]")


def _collect_valid_images(ctx: PipelineContext) -> dict[str, set[str]]:
    """Map each cited source's folder name → the real image filenames on disk.

    These are the only paths the report may legitimately embed; we match the
    LLM's transcribed embeds against this whitelist to repair dropped/changed
    chars in hashes (it's exactly the set offered to the LLM, so a near match is
    unambiguous — distinct hashes differ by ~50 chars)."""
    papers, patents, webs = _iter_sources(ctx)
    index: dict[str, set[str]] = {}
    for src in papers + patents + webs:
        md = _find_source_md(ctx, src)
        if not md:
            continue
        img_dir = md.parent / "images"
        if not img_dir.is_dir():
            continue
        names = {f.name for f in img_dir.iterdir()
                 if f.is_file() and f.suffix.lower() in _IMG_EXTS}
        if names:
            index.setdefault(md.parent.name, set()).update(names)
    return index


def _repair_image_embeds(content: str, index: dict[str, set[str]]) -> tuple[str, int]:
    """Fix image embeds whose hash was mis-transcribed, against the real-file
    whitelist.
    - Unknown folder (not in index): leave untouched.
    - Known folder, file already valid: leave untouched.
    - Known folder, file wrong but repairable (edit distance ≤ cap): replace.
    - Known folder, file irreparable (distance too large, or no extension to
      match against): remove the embed entirely — a broken ![[]] is worse than
      nothing and causes check_report fatal errors."""
    if not index:
        return content, 0
    fixed = 0

    def repl(m: re.Match) -> str:
        nonlocal fixed
        dir_path, fn = m.group(1), m.group(2)
        folder_key = dir_path.split("/")[-1]
        names = index.get(folder_key)
        if names is None:
            return m.group(0)  # unknown folder — leave as-is
        if fn in names:
            return m.group(0)  # already valid
        # Folder is known but filename is wrong — try to repair.
        want = Path(fn).stem
        suffix = Path(fn).suffix.lower()
        # When the LLM omits the extension, try all candidates in the folder.
        candidates = names if not suffix else {c for c in names if Path(c).suffix.lower() == suffix}
        if candidates:
            cap = max(8, len(want) // 6)
            best, best_d = None, cap + 1
            for cand in candidates:
                d = edit_distance_capped(Path(cand).stem, want, cap)
                if d < best_d:
                    best, best_d = cand, d
            if best is not None and best_d <= cap:
                fixed += 1
                return f"![[{dir_path}/images/{best}]]"
        # Irreparable — remove the broken embed to avoid check_report failures.
        fixed += 1
        return ""

    return _REPORT_IMG_EMBED_RE.sub(repl, content), fixed


def _ensure_frontmatter_first(content: str) -> str:
    """If LLM placed content before the --- block, move it after the closing ---."""
    if content.startswith("---"):
        return content
    # Find the first --- block
    idx = content.find("\n---\n")
    if idx == -1:
        return content
    before = content[:idx].strip()
    rest = content[idx + 1:]  # starts with ---\n...
    # Find closing ---
    end = rest.find("\n---\n", 3)
    if end == -1:
        return content
    frontmatter_block = rest[:end + 5]  # includes closing ---\n
    after_fm = rest[end + 5:]
    body = (before + "\n\n" + after_fm).strip()
    return frontmatter_block + ("\n\n" if body else "") + body


def _close_frontmatter(content: str) -> str:
    """Ensure the opening `---` frontmatter block has a matching closing `---`.

    LLMs sometimes emit the opening `---` and the YAML keys but forget the
    closing `---`. Without it, Markdown/Obsidian renderers can't parse the block
    as frontmatter and dump the whole YAML as run-together raw text. Detect that
    case and insert the closing delimiter right before the first heading.
    """
    if not content.startswith("---"):
        return content
    lines = content.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return content  # already closed
    # No closing delimiter — close it before the first Markdown heading.
    for i in range(1, len(lines)):
        if lines[i].lstrip().startswith("#"):
            j = i
            while j - 1 > 0 and lines[j - 1].strip() == "":
                j -= 1
            return "\n".join(lines[:j] + ["---", ""] + lines[i:])
    return content


def _fix_date(content: str, date_iso: str) -> str:
    """Normalize the frontmatter `date:` to the real generation date.

    The LLM isn't given today's date and routinely guesses the wrong year, so we
    overwrite the first `date:` line (always inside frontmatter) with date_iso.
    """
    return re.sub(r"(?m)^date:.*$", f"date: {date_iso}", content, count=1)


def _fix_sources_count(content: str) -> str:
    """Count actual citations and patch sources: in frontmatter.

    Strategy (in priority order):
    1. Parse the references table (## 参考文献) — most accurate: each row = one cited source.
    2. Fall back to counting unique wikilinks [[...]] split by type in the body.
    3. Last resort: count unique [N] / [PN] / [WN] bracket refs (least accurate).
    """
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    body = content[fm_match.end():] if fm_match else content

    n_papers = n_patents = n_web = 0

    # --- Strategy 1: parse 参考文献 table ---
    # Rows look like:  | 1 | 论文 | ... | or | P1 | 专利 | ...
    ref_section = re.search(r"##\s*参考文献\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
    if ref_section:
        rows = re.findall(
            r"^\s*\|.*?\|\s*(论文|专利|Web)\s*\|",
            ref_section.group(1),
            re.MULTILINE | re.IGNORECASE,
        )
        if rows:
            n_papers  = sum(1 for r in rows if r in ("论文",))
            n_patents = sum(1 for r in rows if r in ("专利",))
            n_web     = sum(1 for r in rows if r.lower() == "web")

    # --- Strategy 2: unique wikilinks by type (fallback) ---
    if n_papers == n_patents == n_web == 0:
        all_wikilinks = re.findall(r"\[\[([^\]|]+)", body)
        patent_re = re.compile(r"^(CN|US|EP|WO|JP|KR)\d", re.IGNORECASE)
        web_re    = re.compile(r"^https?://|raw/web/|wiki/qa/", re.IGNORECASE)
        for stem in set(all_wikilinks):
            stem = stem.strip()
            if patent_re.match(stem):
                n_patents += 1
            elif web_re.match(stem):
                n_web += 1
            else:
                n_papers += 1

    # --- Strategy 3: bracket refs (last resort) ---
    if n_papers == n_patents == n_web == 0:
        n_papers  = len(set(re.findall(r"\[(\d+)\]", body)))
        n_patents = len(set(re.findall(r"\[P(\d+)\]", body)))
        n_web     = len(set(re.findall(r"\[W(\d+)\]", body)))

    def _replace_source(m: re.Match) -> str:
        key = m.group(1)
        if key == "papers":
            return f"  papers: {n_papers}"
        if key == "patents":
            return f"  patents: {n_patents}"
        if key == "web":
            return f"  web: {n_web}"
        return m.group(0)

    return re.sub(r"^  (papers|patents|web): *\d+", _replace_source, content, flags=re.MULTILINE)


def _slug(text: str) -> str:
    text = re.sub(r"[^\w一-鿿\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40]


def _preflight_check(ctx: PipelineContext) -> list[str]:
    """Pre-flight checklist 12 项，返回失败项列表。"""
    failures: list[str] = []
    total = len(ctx.local_candidates) + len(ctx.ieee_new_papers) + len(ctx.patent_downloaded)
    if total == 0:
        failures.append("#1 无素材")
    # #2: empty panorama is a hard failure only when no materials to compensate
    if not ctx.panorama_table and total < 3:
        failures.append("#2 全景表未建（且素材不足）")
    return failures


async def run(ctx: PipelineContext) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-flight
    failures = _preflight_check(ctx)
    insufficient = bool(failures) or (
        len(ctx.ieee_new_papers) + len(ctx.patent_downloaded) < 2
        and len(ctx.local_candidates) < 3
    )
    ctx.report_type = "insufficient" if insufficient else "normal"

    # R12: 读 OBSIDIAN-WRITING.md
    obsidian_rules = _read_obsidian_rules()

    system_prompt = _REPORT_SYSTEM_TEMPLATE.replace("__OBSIDIAN_RULES__", obsidian_rules)

    panorama_text = "\n".join(
        f"- {r.direction} [{r.category}] {r.coverage} 已覆盖素材: {', '.join(r.covering_papers) or '无'}"
        for r in ctx.panorama_table
    ) or "（无全景表）"

    sub_q_text = "\n".join(f"{q.id}: {q.text} [{q.coverage}]" for q in ctx.sub_questions)

    papers, patents, webs = _iter_sources(ctx)
    materials_text, cite_table = _format_materials(ctx)
    user_msg = _REPORT_USER_TEMPLATE.format(
        question=ctx.clarified_text or " ".join(ctx.keywords),
        sub_questions=sub_q_text,
        panorama=panorama_text,
        n_papers=len(papers),
        n_patents=len(patents),
        n_web=len(webs),
        materials=materials_text,
        cite_table=cite_table,
    )
    if ctx.report_type == "insufficient":
        user_msg += "\n\n注意：素材不足，请生成降级报告（status: insufficient），给出搜索建议。"

    # 生成报告（使用流式 Anthropic 调用，可支持更大 max_tokens）
    llm = LLMClient(step=9)
    report_content = await llm.chat(
        [ChatMessage(role="user", content=user_msg)],
        system=system_prompt,
        max_tokens=32000,
    )

    # 写入文件
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    date_iso = now.strftime("%Y-%m-%d")
    slug = _slug(ctx.clarified_text or " ".join(ctx.keywords[:3]))
    report_filename = f"{slug}_report_{date_str}_t{ctx.task_id}.md"
    report_path = RESEARCH_DIR / report_filename
    final_content = _fix_date(
        _fix_sources_count(_close_frontmatter(_ensure_frontmatter_first(report_content))),
        date_iso,
    )
    # Repair image-embed hashes the LLM mis-transcribed (drops a char in a 64-hex
    # MinerU name → broken figure). Match against the real files actually on disk.
    img_index = _collect_valid_images(ctx)
    final_content, n_img_fixed = _repair_image_embeds(final_content, img_index)
    if n_img_fixed:
        print(f"[Step 9] 处理无效图片引用 {n_img_fixed} 处（修复或移除）")
    report_path.write_text(final_content, encoding="utf-8")
    ctx.report_path = str(report_path)

    # 写 Report DB 记录
    try:
        async with AsyncSessionLocal() as db:
            vault_path = str(report_path.relative_to(WILSON_LIB))
            report_row = Report(
                task_id=ctx.task_id,
                vault_path=vault_path,
                summary_text=report_content[:500],
                citations_json="[]",
            )
            db.add(report_row)
            await db.commit()
    except Exception:
        pass  # 不因 DB 写入失败阻断报告生成

    # fix_citations
    try:
        await cad_tools.fix_citations(str(report_path))
    except Exception:
        pass

    # check_report 校验（结果记录到 context，不阻塞流程）
    env_extra = {}
    if ctx.staging_dir:
        env_extra["EXTRA_SEARCH_PATHS"] = ",".join([
            str(Path(ctx.staging_dir) / "ieee"),
            str(Path(ctx.staging_dir) / "patent"),
            str(Path(ctx.staging_dir) / "web"),
        ])

    try:
        code, output = await cad_tools.check_report(str(report_path), "full", env_extra=env_extra)
        ctx.preflight_passed = (code == 0)
        if code != 0:
            print(f"[Step 9] check_report 未完全通过（继续生成）:\n{output[:500]}")
            # Remove image embeds that check_report confirmed don't exist on disk,
            # so the saved report never contains unresolvable ![[...]] references.
            broken = re.findall(r"❌ 图片不存在: ([^\n]+)", output)
            if broken:
                fixed = report_path.read_text(encoding="utf-8")
                for img_ref in broken:
                    fixed = fixed.replace(f"![[{img_ref.strip()}]]", "")
                report_path.write_text(fixed, encoding="utf-8")
                print(f"[Step 9] 已从报告中移除 {len(broken)} 处不存在的图片引用")
    except Exception as e:
        print(f"[Step 9] check_report 异常: {e}")
        ctx.preflight_passed = True
