#!/usr/bin/env python3
"""DuckDuckGo HTML 搜索脚本（零依赖，纯 stdlib）。

用法:
  python web_search.py "Class-D amplifier PSRR"           # 搜索返回摘要
  python web_search.py "SAR ADC switching" --max 10 --json # JSON 输出
  python web_search.py "buck converter EMI" --save raw/web/Power/  # 保存结果 MD
"""

import argparse
import html as _html
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

DDG_HTML = "https://html.duckduckgo.com/html/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


# 跳过学术/专利 URL（论文和专利有专用搜索路径）
_SKIP_DOMAINS = [
    "ieeexplore.ieee.org",       # IEEE 论文
    "patents.google.com",        # Google Patents
    "patentimages.storage.googleapis.com",
    "scholar.google",            # Google Scholar
    "arxiv.org",                 # arXiv
    "dl.acm.org",                # ACM
    "link.springer.com",         # Springer
    "sciencedirect.com",         # Elsevier
    "onlinelibrary.wiley.com",   # Wiley
    "repository.tudelft.nl",     # TU Delft 学术仓库
    "hal.science",               # HAL 开放档案
    "dr.ntu.edu.sg",             # NTU 学术仓库
    "researchgate.net",          # ResearchGate
    "semanticscholar.org",       # Semantic Scholar
    "academia.edu",              # Academia.edu
]


def _is_academic(url: str) -> bool:
    """检查 URL 是否属于学术论文/专利源（应跳过）。"""
    for d in _SKIP_DOMAINS:
        if d in url:
            return True
    return False


def search(query: str, max_results: int = 10, timeout: int = 30, retries: int = 2) -> list[dict]:
    """搜索 DDG HTML 版，返回 [{title, url, snippet}, ...]。自动跳过论文/专利源。

    timeout: 单次请求超时秒数（默认 30s）
    retries: 超时/失败后重试次数（默认 2，即最多 3 次尝试）
    """
    # 请求更多结果以补偿过滤损失
    fetch_n = min(max_results * 3, 30)
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(DDG_HTML, data=data, headers=HEADERS)
    last_err = None
    for attempt in range(1 + retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            break  # 成功，跳出重试循环
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = 3 * (attempt + 1)  # 3s, 6s, ...
                print(f"[warn] 搜索第 {attempt+1} 次失败: {e}，{wait}s 后重试…", file=sys.stderr)
                time.sleep(wait)
    else:
        print(f"[error] 搜索失败（{1+retries} 次尝试均超时/失败）: {last_err}", file=sys.stderr)
        return []

    results = []
    # 提取每个结果块：class="result" 的 div
    blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*result|\Z)', html, re.DOTALL)
    if not blocks:
        blocks = re.findall(r'<div[^>]*class="[^"]*result__body[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)

    for block in blocks[:max_results]:
        # 提取标题+链接
        link_m = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not link_m:
            link_m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not link_m:
            continue

        url = _html.unescape(link_m.group(1))
        title = re.sub(r'<[^>]+>', '', link_m.group(2)).strip()
        title = _html.unescape(title)

        # 提取摘要
        snippet_m = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet = ""
        if snippet_m:
            snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()
            snippet = _html.unescape(snippet)
        else:
            # fallback: 取 block 中非链接文本
            clean = re.sub(r'<a[^>]*>.*?</a>', '', block, flags=re.DOTALL)
            clean = re.sub(r'<[^>]+>', ' ', clean)
            snippet = ' '.join(clean.split())[:300]

        # 跳过学术/专利源
        if _is_academic(url):
            continue

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break

    return results


def fetch_content(url: str) -> tuple[str, str]:
    """抓取 URL 内容，返回 (content_type, text)。
    - HTML → 去标签纯文本
    - PDF → 返回提示，不下载
    """
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ct = resp.headers.get("Content-Type", "")
            data = resp.read()
    except Exception as e:
        return "", f"[fetch error] {e}"

    if "pdf" in ct.lower() or url.endswith(".pdf"):
        return "pdf", f"> ⚠️ PDF 文件，请用 ieee_search.py 或手动下载\n> {url}"

    text = data.decode("utf-8", errors="replace")
    # 去 script/style
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', text, flags=re.DOTALL)
    # 去 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)
    # 去 HTML 实体
    text = _html.unescape(text)
    # 压缩空白
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # 截断（网页可能很长）
    lines = text.split('\n')
    trimmed = []
    chars = 0
    for line in lines:
        if line.strip():
            trimmed.append(line.strip())
            chars += len(line)
            if chars > 8000:
                trimmed.append("\n... (截断，完整内容见原文)")
                break
    return "html", "\n\n".join(trimmed)


def save_md(results: list[dict], query: str, out_dir: pathlib.Path, fetch: bool = False):
    """保存搜索结果到 MD 文件。fetch=True 时抓取全文。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^\w]+', '_', query.strip())[:60]
    fname = f"web_{slug}_{time.strftime('%Y%m%d')}.md"
    fpath = out_dir / fname

    lines = [
        "---",
        f"title: Web 搜索: {query}",
        f"tags: [web-clipping]",
        f"created: {time.strftime('%Y-%m-%d')}",
        f"source: DuckDuckGo",
        "---",
        "",
        f"# {query}",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r['title']}")
        lines.append(f"- **URL**: {r['url']}")
        lines.append(f"- **摘要**: {r['snippet']}")
        if fetch and r['url'].startswith("http"):
            ct, text = fetch_content(r['url'])
            if ct == "pdf":
                lines.append(f"- **全文**: {text}")
            elif text:
                lines.append(f"\n{text}\n")
        lines.append("")

    fpath.write_text("\n".join(lines), encoding="utf-8")
    print(f"[saved] {fpath}")
    return fpath


def main():
    parser = argparse.ArgumentParser(description="DuckDuckGo HTML 搜索")
    parser.add_argument("query", help="搜索关键词")
    parser.add_argument("--max", type=int, default=10, help="最大返回数 (default: 10)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--save", type=str, default=None, metavar="DIR",
                        help="保存结果 MD 到指定目录（vault 相对路径）")
    parser.add_argument("--fetch", action="store_true",
                        help="抓取每个结果的网页全文（与 --save 配合使用）")
    parser.add_argument("--select", type=str, default=None, metavar="1,3,5",
                        help="仅保存/抓取指定序号的结果（如 --select 1,3,5）")
    parser.add_argument("--timeout", type=int, default=30,
                        help="单次请求超时秒数（默认 30s）")
    parser.add_argument("--retries", type=int, default=2,
                        help="超时/失败后重试次数（默认 2，即最多 3 次尝试）")

    args = parser.parse_args()

    results = search(args.query, args.max, timeout=args.timeout, retries=args.retries)

    # --select 过滤
    if args.select:
        indices = set()
        for part in args.select.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                indices.update(range(int(a), int(b) + 1))
            else:
                indices.add(int(part))
        results = [r for i, r in enumerate(results, 1) if i in indices]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(results, 1):
            print(f"{i}. {r['title']}")
            print(f"   {r['url']}")
            if r['snippet']:
                print(f"   {r['snippet'][:200]}")
            print()

    if args.save:
        vault = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))
        out_dir = vault / args.save
        save_md(results, args.query, out_dir, fetch=args.fetch)


if __name__ == "__main__":
    main()
