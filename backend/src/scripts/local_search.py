#!/usr/bin/env python3
"""本地 vault 搜索：用关键词搜 ieee_paper_md/ + patent_md/，输出 JSON 命中列表。

无 LLM 依赖。关键词直接从命令行传入或由调用方（Claude Code skill）提取。

用法:
  python local_search.py "Class-D THD amplifier"
  python local_search.py "MEMS gyroscope Allan" --json
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

_RG_BIN: str | None = shutil.which("rg")

_WILSON_LIB = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))
VAULT = _WILSON_LIB / "ieee_paper_md"
PATENT_MD = _WILSON_LIB / "patent_md"

# 单词兜底搜索时排除的泛词：英文虚词 + 模拟 IC 论文里无处不在的结构词。
# 这些词（尤其 gate/drive/control/level/circuit/design）几乎命中每篇论文，
# 若参与单词兜底会把大量无关文献误召回（如 "GaN gate driver" 命中所有含 "gate" 的带隙论文）。
# 注意：保留 reference/temperature/bandgap/hemt/gan/cmti/bridge 等区分性强的词。
_FALLBACK_STOPWORDS = frozenset((
    'and', 'for', 'the', 'with', 'that', 'this', 'from', 'are', 'was', 'has',
    'have', 'can', 'will', 'its', 'out', 'use', 'used', 'using', 'based', 'via',
    'than', 'then', 'into', 'over', 'under', 'such', 'also', 'new', 'novel',
    'gate', 'drive', 'driver', 'control', 'level', 'circuit', 'design', 'voltage',
    'current', 'power', 'high', 'low', 'stage', 'mode', 'output', 'input', 'signal',
    'system', 'method', 'device', 'technology', 'application', 'performance', 'proposed',
))


def grep_files(pattern: str, path: pathlib.Path, max_results: int = 30,
               whole_word: bool = False) -> list[str]:
    """rg 搜索 .md 文件，返回命中文件路径列表；rg 不可用时降级到 grep。

    whole_word=True 用 -w 全词匹配，避免短词作为子串误命中。
    """
    if not path.exists():
        return []

    rg = _RG_BIN
    if rg:
        args = [rg, "-i", "-l", "--no-ignore", "-g", "*.md"]
        if whole_word:
            args.append("-w")
        try:
            result = subprocess.run(
                args + [pattern, str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
            )
            return result.stdout.strip().splitlines()[:max_results]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # fall through to grep

    grep_args = ["/usr/bin/grep", "-r", "-i", "-l", "--include=*.md"]
    if whole_word:
        grep_args.append("-w")
    try:
        result = subprocess.run(
            grep_args + [pattern, str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
        return result.stdout.strip().splitlines()[:max_results]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # 降级：Python 原生扫描
        hits = []
        pat = pattern.lower()
        for f in path.rglob("*.md"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore").lower()
                matched = (
                    bool(re.search(rf"\b{re.escape(pat)}\b", text)) if whole_word
                    else pat in text
                )
                if matched:
                    hits.append(str(f))
                    if len(hits) >= max_results:
                        break
            except Exception:
                continue
        return hits


def search_vault(keywords: list[str]) -> dict:
    """用关键词列表搜索 vault，返回结构化命中结果。

    多关键词加权排序：每篇论文按匹配关键词数计分，得分高的排前，
    避免单关键词结果占满 30 个位置导致其他关键词命中被截断。
    """
    papers: list[str] = []
    patents: list[str] = []

    # 收集每个文件匹配的关键词数
    paper_scores: dict[str, int] = {}
    patent_scores: dict[str, int] = {}
    report_scores: dict[str, int] = {}

    for kw in keywords[:6]:
        kw = kw.strip()
        if not kw or len(kw) < 2:
            continue

        # 1. ieee_paper_md/ → 论文 MD
        for f in grep_files(kw, VAULT):
            paper_scores[f] = paper_scores.get(f, 0) + 1

        # 2. patent_md/ → 专利 MD
        for f in grep_files(kw, PATENT_MD):
            patent_scores[f] = patent_scores.get(f, 0) + 1

    # 短语匹配召回太少时，自动拆词补搜（防短语太严漏掉论文）
    if len(paper_scores) < 15:
        all_words = set()
        for kw in keywords[:6]:
            for w in kw.strip().split():
                w = w.strip().lower()
                if len(w) >= 3 and w not in _FALLBACK_STOPWORDS:
                    all_words.add(w)
        for w in all_words:
            for f in grep_files(w, VAULT, whole_word=True):
                paper_scores[f] = paper_scores.get(f, 0) + 1
            for f in grep_files(w, PATENT_MD, whole_word=True):
                patent_scores[f] = patent_scores.get(f, 0) + 1

    papers = sorted(paper_scores.keys(),
                    key=lambda f: (-paper_scores[f], f))[:40]
    patents = sorted(patent_scores.keys(),
                     key=lambda f: (-patent_scores[f], f))[:30]
    reports = sorted(report_scores.keys(),
                     key=lambda f: (-report_scores[f], f))[:10]

    total = len(papers) + len(patents)
    sufficient = total >= 5

    return {
        "keywords": keywords,
        "papers": papers,
        "patents": patents,
        "reports": reports,
        "sufficient": sufficient,
        "sufficient_warning": "⚠️ sufficient 是纯数量判断，Claude 必须独立做语义评估（→ R6）" if sufficient else None,
        "counts": {
            "papers": len(papers),
            "patents": len(patents),
            "reports": len(reports),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="本地 vault 关键词搜索")
    parser.add_argument("keywords", nargs="+", help="搜索关键词（空格分隔，每个词单独搜索）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON（默认只输出摘要）")
    args = parser.parse_args()

    result = search_vault(args.keywords)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        c = result["counts"]
        print(f"关键词：{' '.join(result['keywords'])}")
        print(f"素材：论文 {c['papers']} 篇，专利 {c['patents']} 篇，历史报告 {c['reports']} 篇")
        suf_label = '✅' if result['sufficient'] else '❌'
        print(f"充足：{suf_label}")
        if result['sufficient_warning']:
            print(f"  {result['sufficient_warning']}")
        if result["papers"]:
            print(f"论文（前10）：")
            for p in result["papers"][:10]:
                print(f"  {pathlib.Path(p).name}")
        if result["patents"]:
            print(f"专利（前10）：")
            for p in result["patents"][:10]:
                print(f"  {pathlib.Path(p).name}")
        if result["reports"]:
            print(f"历史报告（前5）：")
            for p in result["reports"][:5]:
                print(f"  {pathlib.Path(p).name}")

    sys.exit(0)  # sufficient 仅 JSON 字段输出，退出码不承载语义（R6）


if __name__ == "__main__":
    main()
