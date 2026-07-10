#!/usr/bin/env python3
"""Google Scholar 搜索：通过 Playwright CDP 连接 Chrome，解析 Scholar HTML 结果。

与 ieee_search.py 复用同一个 Chrome CDP session，不需要额外登录。

用法:
  python scholar_search.py MEMS resonator temperature
  python scholar_search.py "Class-D amplifier THD" --max 10 --json

输出 paper dict 格式与 ieee_search 兼容：
  {title, doi, year, cited_by, url, authors, snippet, source}
"""

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _cdp_helper import ensure_cdp, get_cdp_ws_url


SCHOLAR_HOME = "https://scholar.google.com"
CURRENT_YEAR = date.today().year
YEAR_MIN = CURRENT_YEAR - 15

DOI_RE = re.compile(r'\b10\.\d{4,}/[^\s"\'<>]+', re.I)


def extract_doi(text: str, url: str = "") -> str:
    """从文本或 URL 中提取 DOI。"""
    # 优先从 URL 提取
    if url:
        m = DOI_RE.search(url)
        if m:
            return m.group().rstrip(".,;:)")
        # 有些 URL 含 DOI 但格式不同
        if "doi.org/" in url.lower():
            doi_part = url.lower().split("doi.org/", 1)[1].split("?")[0].split("&")[0]
            return doi_part
    # 从文本提取
    if text:
        m = DOI_RE.search(text)
        if m:
            return m.group().rstrip(".,;:)")
    return ""


def extract_cited_by(text: str) -> int:
    """从 'Cited by 123' 字符串提取引用数。"""
    m = re.search(r'Cited by (\d[\d,]*)', text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


def search_scholar(page, query: str, max_results: int = 20, year_min: int = YEAR_MIN) -> list[dict]:
    """搜索 Google Scholar，解析 HTML 结果。

    用同一 Chrome CDP 页面导航 Scholar，解析搜索结果 DOM。
    """
    params = {
        "q": query,
        "as_ylo": str(year_min),
        "num": str(min(max_results, 20)),
        "hl": "en",
    }
    url = f"{SCHOLAR_HOME}/scholar?{urllib.parse.urlencode(params)}"
    print(f"[scholar] 搜索: {query[:60]} (year>={year_min})", flush=True)

    # 导航 + 等待页面渲染
    SCHOLAR_RESULT_SELECTOR = "div.gs_r"

    # 预热：先导航 Scholar 首页建立 session
    try:
        page.goto(SCHOLAR_HOME, wait_until="domcontentloaded", timeout=15000)
        time.sleep(1.5)
    except Exception:
        pass

    # 搜索
    try:
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(3)  # 等 JS 完全渲染
    except Exception as e:
        print(f"[scholar] 页面加载失败: {e}", flush=True)
        return []

    # 确认结果存在
    count = page.evaluate(f"() => document.querySelectorAll('{SCHOLAR_RESULT_SELECTOR}').length")
    if count == 0:
        # 检查是否 CAPTCHA
        try:
            body = page.content().lower()
        except Exception:
            body = ""
        if "recaptcha" in body:
            print("[scholar] ⚠️  CAPTCHA — 请在 Chrome 手动验证后重跑", flush=True)
        else:
            print("[scholar] ⚠️  未找到结果", flush=True)
        return []

    # 解析搜索结果 DOM
    papers = page.evaluate("""() => {
        const results = [];
        // Scholar 的多种容器
        const items = document.querySelectorAll('div.gs_r');
        items.forEach(el => {
            // 标题 + 链接 (多种可能结构)
            let titleEl = el.querySelector('h3.gs_rt > a');
            if (!titleEl) titleEl = el.querySelector('h3 > a');
            if (!titleEl) titleEl = el.querySelector('a[data-clk]');
            if (!titleEl) return;
            const title = titleEl.textContent.trim();
            if (title.length < 10) return;
            const url = titleEl.href || '';

            // 摘要
            const snippetEl = el.querySelector('div.gs_rs');
            const snippet = snippetEl ? snippetEl.textContent.trim() : '';

            // 作者/年份/期刊 (div.gs_a 包含绿色一行)
            const metaEl = el.querySelector('div.gs_a');
            const meta = metaEl ? metaEl.textContent.trim() : '';

            // 被引用数 (找含 "Cited by" 的链接)
            let citedBy = 0;
            const allLinks = el.querySelectorAll('a');
            allLinks.forEach(a => {
                const txt = a.textContent.trim();
                const m = txt.match(/Cited by (\\d[\\d,]*)/i);
                if (m) citedBy = parseInt(m[1].replace(/,/g, ''), 10);
            });

            // 年份提取
            let year = 0;
            const yrMatch = meta.match(/(?:^|[^\\d])(19\\d{2}|20\\d{2})(?:[^\\d]|$)/);
            if (yrMatch) year = parseInt(yrMatch[1], 10);

            results.push({title, url, snippet, meta, citedBy, year});
        });
        return results;
    }""")

    print(f"[scholar] HTML 解析到 {len(papers)} 篇", flush=True)

    # 统一格式 + 提取 DOI
    out = []
    for p in papers:
        doi = extract_doi(p.get("snippet", "") + p.get("meta", ""), p.get("url", ""))
        cited = p.get("citedBy", 0)
        year = p.get("year", 0)
        if year < year_min:
            year = 0  # 无法提取年份，保留

        out.append({
            "title": p.get("title", ""),
            "doi": doi,
            "year": year,
            "cited_by": cited,
            "url": p.get("url", ""),
            "authors": "",  # Scholar 解析不加作者（可在后续从论文页提取）
            "snippet": p.get("snippet", "")[:200],
            "venue": "",
            "source": "scholar",
        })

    # 按引用数降序
    out.sort(key=lambda x: x["cited_by"], reverse=True)
    return out


def merge_papers(ieee_papers: list[dict], scholar_papers: list[dict]) -> list[dict]:
    """合并 IEEE + Scholar 结果，按 DOI (lowercase) 或 title (前80字符) 去重。"""
    merged: dict[str, dict] = {}

    def _key(p: dict) -> str:
        doi = (p.get("doi") or "").strip().lower()
        if doi:
            return f"doi:{doi}"
        title = (p.get("title") or "").strip().lower()[:80]
        return f"title:{title}"

    for p in ieee_papers:
        key = _key(p)
        if not key or key == "title:":
            continue
        p["source"] = "ieee"
        merged[key] = p

    new_count = 0
    for p in scholar_papers:
        key = _key(p)
        if not key or key == "title:":
            continue
        if key in merged:
            existing = merged[key]
            if p.get("cited_by", 0) > existing.get("cited_by", 0):
                existing["cited_by"] = p["cited_by"]
            if not existing.get("doi") and p.get("doi"):
                existing["doi"] = p["doi"]
            existing["source"] = "both"
        else:
            p["source"] = "scholar"
            merged[key] = p
            new_count += 1

    result = list(merged.values())
    result.sort(key=lambda x: x.get("cited_by", 0), reverse=True)
    print(f"[merge] {len(result)} 篇 (Scholar 新增 {new_count})", flush=True)
    return result


def score_and_select(candidates: list[dict], max_papers: int = 10) -> list[dict]:
    """评选 top N：优先 15 年内 + 高引用。"""
    # 过滤 15 年内
    recent = [p for p in candidates if p.get("year", 0) >= YEAR_MIN]
    old = [p for p in candidates if p.get("year", 0) < YEAR_MIN]

    recent.sort(key=lambda p: p.get("cited_by", 0), reverse=True)
    selected = recent[:max_papers]

    # 如果不够，补旧论文
    if len(selected) < max_papers:
        old.sort(key=lambda p: p.get("cited_by", 0), reverse=True)
        selected += old[:max_papers - len(selected)]

    return selected


def main():
    parser = argparse.ArgumentParser(description="Google Scholar 搜索（需 Playwright CDP）")
    parser.add_argument("query", nargs="+", help="搜索词")
    parser.add_argument("--max", type=int, default=20, help="最大结果数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--year-min", type=int, default=YEAR_MIN)
    args = parser.parse_args()

    query = " ".join(args.query)

    # CDP 检查 + Playwright 连接
    import subprocess as _sp
    cdp_check = _sp.run(
        ["curl", "-s", "http://localhost:9222/json/version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
    )
    if cdp_check.returncode != 0:
        print("[error] Chrome CDP 未启动。运行 launch_research_chrome.sh")
        sys.exit(1)

    from playwright.sync_api import sync_playwright

    if not ensure_cdp():
        print(json.dumps({"error": "CDP not available"}))
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            papers = search_scholar(page, query, max_results=args.max, year_min=args.year_min)
        finally:
            page.close()

    if args.json:
        print(json.dumps(papers, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'#':>3} {'年':>4} {'引用':>5} {'DOI':6} {'标题':.60}")
        print("-" * 85)
        for i, p in enumerate(papers, 1):
            has_doi = "DOI" if p["doi"] else "  —"
            title = p["title"][:55]
            print(f"{i:>3} {p['year']:>4} {p['cited_by']:>5} {has_doi:>4} {title}")


if __name__ == "__main__":
    main()
