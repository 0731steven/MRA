#!/usr/bin/env python3
"""IEEE Xplore 远程搜索下载脚本。

前置条件：pip install playwright && playwright install chromium
Chrome CDP 自动启动（无需手动运行 launch 脚本）。

用法:
  python ieee_search.py "low-power ADC"
  python ieee_search.py "Class-D amplifier THD" --max 10
  python ieee_search.py "MEMS gyroscope" --dry-run   # 仅列出候选，不下载
"""

import argparse
import json
import os
import pathlib
import re
import sys
import random
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _cdp_helper import ensure_cdp, get_cdp_ws_url, check_cdp_port
from paper_manager import categorize

_WILSON_LIB = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))
VAULT = pathlib.Path(os.environ.get("IEEE_MD_OUTPUT", str(_WILSON_LIB / "ieee_paper_md")))
PDF_SRC = pathlib.Path(os.environ.get("IEEE_PDF_SRC", str(pathlib.Path.home() / "Downloads" / "ieee_papers")))


def build_vault_doi_index():
    """扫描 vault 全库，返回已入库的 DOI 集合（跨 topic 查重）。"""
    dois = set()
    if not VAULT.exists():
        return dois
    for d in VAULT.iterdir():
        if not d.is_dir() or d.name.startswith(".") or d.name == "CAD":
            continue
        for paper_dir in d.iterdir():
            if not paper_dir.is_dir():
                continue
            m = re.search(r"_(\d{7,10})$", paper_dir.name)
            if m:
                dois.add(m.group(1))
    return dois

# Force UTF-8 stdout/stderr — playwright/_cdp_helper resets Windows console to GBK,
# causing UnicodeEncodeError on ✅ and other non-GBK symbols.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DOWNLOAD_BASE = pathlib.Path(os.environ.get("IEEE_PDF_SRC", str(pathlib.Path.home() / "Downloads" / "ieee_papers")))
# WebVPN 前缀：http://webvpn.ustb.booktsg.com/https/<encoded_hash>
# 不设时直接访问 ieeexplore.ieee.org
IEEE_WEBVPN_PREFIX = os.environ.get("IEEE_WEBVPN_PREFIX", "")
XPLORE_HOME = IEEE_WEBVPN_PREFIX or "https://ieeexplore.ieee.org"
# jieyoutsg.com 入口链接（访问后自动跳转到 WebVPN IEEE 主页，用于刷新 session）
IEEE_WEBVPN_ENTRY = os.environ.get("IEEE_WEBVPN_ENTRY", "")
# scidownload.com IEEE 入口（访问后直接跳转到 IEEE，用于 auth 失败时的 fallback）
_SCIDOWNLOAD_LIST_URL = "https://www.scidownload.com/e/action/ListInfo/?classid=97"
# 入口链接的 href（相对路径），与列表页上的 <a target="k"> 对应
_SCIDOWNLOAD_ENTRY_HREFS = [
    "/e/action/ShowInfo.php?classid=97&id=2952",
    "/e/action/ShowInfo.php?classid=97&id=2672",
    "/e/action/ShowInfo.php?classid=97&id=5253",
    "/e/action/ShowInfo.php?classid=97&id=5157",
]


def warm_webvpn_session(page) -> None:
    """访问 jieyoutsg.com 入口刷新 WebVPN 机构 session。

    访问后若页面仍在 jieyoutsg.com（跳转未发生），则主动导回 IEEE WebVPN 主页。
    search_xplore 使用相对 URL /rest/search，必须在 WebVPN 页面上下文中执行。
    """
    if not IEEE_WEBVPN_ENTRY:
        return
    print("[auth ] 访问 WebVPN 入口，刷新 session...", flush=True)
    try:
        page.goto(IEEE_WEBVPN_ENTRY, wait_until="load", timeout=30000)
        print(f"[auth ] 入口页已加载，URL: {page.url[:80]}", flush=True)
    except Exception as e:
        print(f"[auth ] ⚠️ 入口页访问失败: {e}", flush=True)
    # 若跳转未发生（仍在 jieyoutsg.com），主动导回 WebVPN 主页
    if "jieyoutsg" in page.url and XPLORE_HOME:
        print("[auth ] 跳转未发生，主动导回 IEEE WebVPN 主页...", flush=True)
        try:
            page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
            time.sleep(1)
            print(f"[auth ] 已到达: {page.url[:80]}", flush=True)
        except Exception as e:
            print(f"[auth ] ⚠️ 导回失败: {e}", flush=True)


def try_scidownload_fallback(page) -> bool:
    """Auth fallback：从 scidownload 列表页点击 IEEE 入口链接（target=k 新窗口），
    等待新窗口跳转到 IEEE，验证认证后导航当前页到 IEEE 主页。

    每次只在失败时尝试下一个入口，成功后立即返回 True。
    全部失败返回 False。
    """
    context = page.context
    print("[auth ] 加载 scidownload 列表页...", flush=True)
    try:
        page.goto(_SCIDOWNLOAD_LIST_URL, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"[auth ] 列表页加载失败: {e}", flush=True)
        return False

    shuffled = _SCIDOWNLOAD_ENTRY_HREFS.copy()
    random.shuffle(shuffled)
    for i, href in enumerate(shuffled, 1):
        print(f"[auth ] 点击 scidownload 入口 {i}/4...", flush=True)
        try:
            # 确保当前页在列表页（入口 2+ 时需要重新导航回来）
            if "scidownload.com" not in page.url:
                page.goto(_SCIDOWNLOAD_LIST_URL, wait_until="load", timeout=30000)

            # 捕获 target="k" 弹出的新窗口
            with context.expect_page(timeout=15000) as new_page_info:
                page.click(f'a[href="{href}"]')
            new_page = new_page_info.value

            # 等待新窗口加载 IEEE 内容（最多 30 秒）
            # jump.php 是代理模式：URL 保持在 doi.downsci.top，但内容是 IEEE
            # 用页面标题判断是否已加载 IEEE
            for waited in range(30):
                cur_url = new_page.url
                cur_title = new_page.title()
                if "ieeexplore.ieee.org" in cur_url or "ieeexplore.ieee.org" in cur_title or "IEEE Xplore" in cur_title:
                    print(f"[auth ] ✅ 新窗口已加载 IEEE ({waited+1}s): {cur_title[:60]}", flush=True)
                    break
                time.sleep(1)
            else:
                print(f"[auth ] 新窗口 30s 内未加载 IEEE，标题: {new_page.title()[:60]}", flush=True)
                new_page.close()
                continue

            new_page.close()
            # 多等几秒让 Shibboleth session cookie 完全写入
            time.sleep(4)
            # 导航当前页到 IEEE 主页（共享 session cookie）
            page.goto("https://ieeexplore.ieee.org", wait_until="load", timeout=30000)
            time.sleep(2)
            if check_auth(page):
                print(f"[auth ] ✅ scidownload 入口 {i} 认证成功", flush=True)
                return True
            print(f"[auth ] 入口 {i} 跳到 IEEE 但认证仍失败，尝试下一个...", flush=True)
        except Exception as e:
            print(f"[auth ] 入口 {i} 失败: {e}", flush=True)

    print("[auth ] ❌ scidownload 4 个入口均失败", flush=True)
    return False


def score_papers(candidates: list[dict], query: str) -> list[dict]:
    """过滤 cited_by < 20 的低质量论文，按引用数降序排列。"""
    filtered = [p for p in candidates if p.get("cited_by", 0) >= 20]
    if not filtered:
        # 无论如何至少返回引用最高的几篇
        filtered = candidates
    return sorted(filtered, key=lambda p: p.get("cited_by", 0), reverse=True)


def search_xplore(page, query: str, max_results: int = 30, page_num: int = 1,
                  fetch_abstracts: bool = False) -> list[dict]:
    """用 REST API 搜索 IEEE Xplore，返回候选论文列表。

    若 fetch_abstracts=True，对每篇论文额外请求 abstract（约 +1s/篇）。
    """
    import json as _json

    print(f"[search] REST API page={page_num}: {query}", flush=True)
    try:
        result = page.evaluate(f"""
        async () => {{
            const resp = await fetch('/rest/search', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'Accept': 'application/json'}},
                body: JSON.stringify({{
                    queryText: {_json.dumps(query)},
                    newsort: 'most_cited',
                    rowsPerPage: {max_results},
                    pageNumber: {page_num},
                    ranges: ['2010_2026_Year']
                }})
            }});
            if (!resp.ok) {{ return {{records: [], totalRecords: 0}}; }}
            const text = await resp.text();
            try {{ return JSON.parse(text); }} catch(e) {{ return {{records: [], totalRecords: 0}}; }}
        }}
        """)
    except Exception as e:
        print(f"[search] page.evaluate 失败: {type(e).__name__}: {str(e)[:100]}", flush=True)
        # Re-navigate and retry once
        try:
            page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
            time.sleep(1.5)
            result = page.evaluate(f"""
            async () => {{
                const resp = await fetch('/rest/search', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'Accept': 'application/json'}},
                    body: JSON.stringify({{
                        queryText: {_json.dumps(query)},
                        newsort: 'most_cited',
                        rowsPerPage: {max_results},
                        pageNumber: {page_num},
                        ranges: ['2010_2026_Year']
                    }})
                }});
                if (!resp.ok) {{ return {{records: [], totalRecords: 0}}; }}
                const text = await resp.text();
                try {{ return JSON.parse(text); }} catch(e) {{ return {{records: [], totalRecords: 0}}; }}
            }}
            """)
        except Exception as e2:
            print(f"[search] 重试也失败: {type(e2).__name__}: {str(e2)[:100]}", flush=True)
            return []

    papers = []
    for r in result.get("records", []):
        article_num = str(r.get("articleNumber", ""))
        abstract = r.get("abstract", "") or r.get("description", "") or ""
        pubtitle = r.get("publicationTitle", "") or ""
        papers.append({
            "title": r.get("articleTitle", ""),
            "doi": article_num,
            "year": int(r.get("publicationYear", 0) or 0),
            "cited_by": int(r.get("citedPaperCount", 0) or 0),
            "url": f"{XPLORE_HOME}/document/{article_num}" if article_num else "",
            "abstract": abstract.strip(),
            "venue": pubtitle.strip(),
        })

    if fetch_abstracts:
        papers = _fetch_abstracts_batch(page, papers)

    return papers


def _fetch_abstracts_batch(page, papers: list[dict]) -> list[dict]:
    """批量获取缺失的 abstract（浏览器内并发 Promise.all，~2s 完成）。"""
    import json as _json

    missing = [(i, p) for i, p in enumerate(papers) if not p.get("abstract")]
    if not missing:
        return papers

    dois_json = _json.dumps([p["doi"] for _, p in missing])
    print(f"[abstract] 并发获取 {len(missing)} 篇摘要...", flush=True)

    try:
        results = page.evaluate(f"""
        async () => {{
            const dois = {dois_json};
            const batch = dois.map(doi =>
                fetch('/rest/search', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ queryText: doi, rowsPerPage: 1, newsearch: true }})
                }})
                .then(r => r.json())
                .then(data => {{
                    const rec = data.records?.[0] || {{}};
                    return {{
                        doi: doi,
                        abstract: rec.abstract || rec.description || '',
                        pubtitle: rec.publicationTitle || '',
                    }};
                }})
                .catch(() => ({{ doi: doi, abstract: '', pubtitle: '' }}))
            );
            return await Promise.all(batch);
        }}
        """)

        for i, (idx, p) in enumerate(missing):
            if i < len(results) and results[i]:
                p["abstract"] = (results[i].get("abstract") or "").strip()
                pub = (results[i].get("pubtitle") or "").strip()
                if pub:
                    p["venue"] = pub

    except Exception as e:
        print(f"[abstract] 并发失败: {e}，降级逐个获取", flush=True)
        for i, (idx, p) in enumerate(missing):
            if p["abstract"]:
                continue
            try:
                abstract = page.evaluate(f"""
                async () => {{
                    const resp = await fetch('/rest/search', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{ queryText: '{p["doi"]}', rowsPerPage: 1, newsearch: true }})
                    }});
                    const data = await resp.json();
                    return (data.records?.[0]?.abstract || data.records?.[0]?.description || '');
                }}
                """)
                p["abstract"] = (abstract or "").strip()
            except Exception:
                pass
            time.sleep(0.2)

    print(f"[abstract] 完成 (含 {sum(1 for p in papers if p.get('abstract'))} 篇摘要)", flush=True)
    return papers


def auth_alert(msg="IEEE 机构认证已失效"):
    """打印醒目的认证失效警告框。"""
    bar = "=" * 60
    print(f"""
{bar}
!!! {msg} !!!
{bar}
  请确认：
  1. Chrome 已登录 IEEE 机构账号（导航到 ieeexplore.ieee.org 检查右上角）
  2. 如已登出，在 Chrome 中重新登录 IEEE 后按 Enter 重试
  3. 如多次失败，关闭所有 Chrome 窗口，重跑 launch_research_chrome.sh
{bar}
""", flush=True)


def check_auth(page, test_doi: str = "11419282") -> bool:
    """Pre-flight auth check：用已知 DOI 试下 PDF，校验 %PDF- 文件头。

    Returns:
        True  — PDF 下载正常
        False — 返回 HTML（登录墙/重定向）
    """
    pdf_url = f"{XPLORE_HOME}/stampPDF/getPDF.jsp?tp=&arnumber={test_doi}"
    captured = []

    def handle_route(route, request):
        try:
            response = route.fetch(timeout=30000)
            ct = response.headers.get("content-type", "")
            if "pdf" in ct or "pdf" in request.url.lower():
                captured.append(response.body())
            route.fulfill(response=response)
        except Exception:
            pass

    route_pattern = f"**/stampPDF/getPDF.jsp*tp=&arnumber={test_doi}*"
    try:
        page.route(route_pattern, handle_route)
        page.goto(pdf_url, wait_until="commit", timeout=45000)
        for _ in range(40):
            if captured:
                break
            page.wait_for_timeout(500)
    except Exception as e:
        print(f"[auth ] 测试请求异常：{type(e).__name__}: {str(e)[:60]}", flush=True)
    finally:
        try:
            page.unroute(route_pattern)
        except Exception:
            pass

    if not captured:
        print("[auth ] 未捕获 PDF 响应", flush=True)
        return False

    body = captured[0]
    if body.startswith(b'%PDF-'):
        print(f"[auth ] ✅ IEEE 认证有效（PDF {len(body)//1024}KB）", flush=True)
        return True
    else:
        # 检测 HTML login 页面关键字
        snippet = body[:2000].decode('utf-8', errors='replace').lower()
        if 'sign in' in snippet or 'login' in snippet or '<html' in snippet:
            print(f"[auth ] ❌ 返回 HTML 登录页 ({len(body)//1024}KB)", flush=True)
        else:
            print(f"[auth ] ❌ 非 PDF 响应 ({len(body)//1024}KB)", flush=True)
        return False


def download_paper(page, paper: dict, topic: str, dry_run: bool = False) -> bool:
    """拦截 stampPDF/getPDF.jsp 响应，直接保存 PDF 字节（与扩展同 URL，无需 chrome.downloads）。"""
    doi = paper.get("doi", "")
    if not doi:
        return False

    if dry_run:
        print(f"  [dry ] {paper['title'][:60]}")
        return False

    dest_dir = DOWNLOAD_BASE / topic
    dest_dir.mkdir(parents=True, exist_ok=True)

    pdf_url = f"{XPLORE_HOME}/stampPDF/getPDF.jsp?tp=&arnumber={doi}"
    import re as _re
    safe_title = _re.sub(r'[<>:"|?*\\/]', '', paper['title'][:60]).replace(' ', '_')
    year = paper.get("year", "0")
    filename = f"{year}_{topic}_{safe_title}_{doi}.pdf"
    save_path = dest_dir / filename

    print(f"  [dl  ] {paper['title'][:55]} ({doi})", flush=True)

    captured = []
    timed_out = False

    def handle_route(route, request):
        try:
            response = route.fetch(timeout=60000)
            ct = response.headers.get("content-type", "")
            if "pdf" in ct or "pdf" in request.url.lower():
                captured.append(response.body())
            route.fulfill(response=response)
        except Exception:
            pass  # 页面已关闭或 route 已处理，静默忽略

    route_pattern = f"**/stampPDF/getPDF.jsp*tp=&arnumber={doi}*"
    try:
        page.route(route_pattern, handle_route)
        page.goto(pdf_url, wait_until="commit", timeout=45000)
        # 等最多 30s 让拦截器捕获
        for _ in range(60):
            if captured:
                break
            page.wait_for_timeout(500)
    except Exception as e:
        err_msg = str(e)[:80]
        if "Timeout" in type(e).__name__ or "timeout" in err_msg.lower():
            timed_out = True
            print(f"  [warn] 导航超时，跳过此篇（{doi}）", flush=True)
        else:
            print(f"  [warn] 导航失败：{type(e).__name__}: {err_msg}", flush=True)
    finally:
        try:
            page.unroute(route_pattern)
        except Exception:
            pass

    if captured:
        body = captured[0]
        # 校验 PDF 文件头，防止 HTML login 页面冒充
        if not body.startswith(b'%PDF-'):
            auth_alert(f"IEEE 认证失效 — {paper['title'][:40]} 下载被拒")
            return False
        save_path.write_bytes(body)
        print(f"  [ok  ] 已保存 {save_path.name} ({len(body)//1024}KB)", flush=True)
        return True
    elif timed_out:
        # 超时 ≠ 认证失效，直接返回 False 让调用方跳过
        return False
    else:
        auth_alert("IEEE 认证失效 — 未捕获 PDF 响应")
        return False


def _fallback_scan_downloads(topic: str, paper: dict) -> bool:
    """降级：扫描 ~/Downloads/ 新增 PDF，按 categorize 移动到正确 topic 目录。"""
    downloads = pathlib.Path("~/Downloads").expanduser()
    new_pdfs = [
        f for f in downloads.glob("*.pdf")
        if (time.time() - f.stat().st_mtime) < 60
    ]
    if not new_pdfs:
        return False

    for pdf in new_pdfs:
        guessed_topic = categorize(paper["title"]) or topic
        dest = DOWNLOAD_BASE / guessed_topic
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / pdf.name
        pdf.rename(target)
        print(f"  [move] {pdf.name} → {guessed_topic}/")
    return len(new_pdfs) > 0


def search_and_download(query: str, max_papers: int = 10, dry_run: bool = False) -> list[str]:
    """主流程：搜索 → 评分 → 下载，返回下载成功的 DOI 列表。"""
    # 检查 CDP 端口
    if not ensure_cdp():
        print("[error] 无法启动研究 Chrome")
        sys.exit(1)

    # 获取 vault 已有 DOI（去重）
    print("[dedup] 读取 vault DOI 索引...")
    existing_dois = build_vault_doi_index()
    print(f"[dedup] vault 已有 {len(existing_dois)} 篇")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[error] playwright 未安装。运行：pip install playwright && playwright install chromium")
        sys.exit(1)

    downloaded_dois = []

    with sync_playwright() as pw:
        ws = get_cdp_ws_url()
        print(f"[cdp  ] 连接 {ws}...")
        browser = pw.chromium.connect_over_cdp(ws)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        # 导航到主页确保 session cookie 有效
        print("[init ] 导航 IEEE Xplore 主页...", flush=True)
        try:
            page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
        except Exception as e:
            print(f"[warn ] 主页导航失败：{e}，继续尝试搜索")
        time.sleep(2)

        # ── Pre-flight auth check ──
        warm_webvpn_session(page)
        print("[auth ] 检查 IEEE 机构认证...", flush=True)
        auth_ok = check_auth(page)
        if not auth_ok:
            print("[auth ] 直连认证失败，尝试 scidownload 入口...", flush=True)
            auth_ok = try_scidownload_fallback(page)
        if not auth_ok:
            auth_alert("下载前认证检查失败")
            try:
                while True:
                    resp = input("  在 Chrome 中登录 IEEE 后输入 r 重试 / q 退出：").strip().lower()
                    if resp == 'r':
                        try:
                            page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
                            time.sleep(2)
                        except Exception:
                            pass
                        if check_auth(page):
                            print("[auth ] ✅ 认证已恢复，继续下载")
                            break
                    elif resp == 'q':
                        print("[exit ] 用户取消")
                        return []
            except (EOFError, OSError):
                print("[exit ] 非交互环境，跳过远程抓取。请在 Chrome 重新登录 IEEE 后重跑。", flush=True)
                return []
            time.sleep(1)

        # REST API 搜索（最多 3 页）
        all_candidates = []
        for page_num in range(1, 4):
            candidates = search_xplore(page, query, max_results=25, page_num=page_num)
            if not candidates:
                break
            all_candidates.extend(candidates)
            if len(candidates) < 20:
                break
            time.sleep(1.5)

        print(f"[found] 共 {len(all_candidates)} 篇候选")

        # 过滤已有 DOI
        new_candidates = [p for p in all_candidates if p["doi"] not in existing_dois]
        print(f"[new  ] 过滤后 {len(new_candidates)} 篇新论文")

        if not new_candidates:
            print("[done ] vault 已包含所有搜索结果")
            return []

        # LLM 评分选 top N
        scored = score_papers(new_candidates, query)
        to_download = scored[:max_papers]
        if len(scored) > max_papers:
            print(f"[score] 评分后 {len(scored)} 篇候选，选定 top {len(to_download)} 篇下载")
            print(f"[warn ] 还有 {len(scored) - max_papers} 篇候选未下载，需手动用 --search-only + --dois 指定")
        else:
            print(f"[score] 选定 {len(to_download)} 篇下载")

        # 按 topic 分类并下载
        failed_papers = []
        for paper in to_download:
            topic = categorize(paper["title"]) or "Amplifier"
            time.sleep(2)  # 礼貌间隔，避免触发反爬

            ok = download_paper(page, paper, topic, dry_run=dry_run)
            if not ok and not dry_run:
                # Auth 失效 → 暂停等待用户恢复
                try:
                    while True:
                        resp = input("  在 Chrome 中重新登录 IEEE 后输入 r 重试 / s 跳过 / q 退出：").strip().lower()
                        if resp == 'r':
                            try:
                                page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
                                time.sleep(2)
                            except Exception:
                                pass
                            ok = download_paper(page, paper, topic, dry_run=False)
                            if ok:
                                if paper["doi"]:
                                    downloaded_dois.append(paper["doi"])
                                break
                        elif resp == 's':
                            failed_papers.append(paper)
                            print(f"  [skip] {paper['title'][:40]}")
                            break
                        elif resp == 'q':
                            print("[exit ] 用户取消")
                            return downloaded_dois
                except (EOFError, OSError):
                    failed_papers.append(paper)
                    print(f"  [skip] 非交互环境，跳过 {paper['title'][:40]}", flush=True)
                    break
            elif ok and paper["doi"]:
                downloaded_dois.append(paper["doi"])

        if failed_papers:
            print(f"\n[warn ] {len(failed_papers)} 篇未下载：")
            for p in failed_papers:
                print(f"  - {p['title'][:60]}")

        page.close()

    print(f"\n[done ] 下载完成：{len(downloaded_dois)} 篇")
    return downloaded_dois


def search_candidates(query: str, max_candidates: int = 75,
                      fetch_abstracts: bool = False) -> list[dict]:
    """仅搜索，不下载。返回候选论文列表（去重 vault 已有 DOI）。"""
    if not ensure_cdp():
        print("[error] 无法启动研究 Chrome")
        sys.exit(1)

    print("[dedup] 读取 vault DOI 索引...")
    existing_dois = build_vault_doi_index()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[error] playwright 未安装")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            try:
                page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            warm_webvpn_session(page)

            # 搜索全部 3 页
            all_candidates = []
            for pn in range(1, 4):
                cands = search_xplore(page, query, max_results=25, page_num=pn,
                                      fetch_abstracts=False)
                if not cands:
                    break
                all_candidates.extend(cands)
                if len(cands) < 20:
                    break
                time.sleep(1.5)
        finally:
            page.close()

    print(f"[found] {len(all_candidates)} 篇候选", flush=True)

    # 去重
    new_candidates = [p for p in all_candidates if p["doi"] not in existing_dois]
    print(f"[new  ] 过滤后 {len(new_candidates)} 篇新论文", flush=True)

    # 如需 abstract，批量获取
    if fetch_abstracts and new_candidates:
        # open second CDP page for abstracts
        try:
            from playwright.sync_api import sync_playwright as _sp2
            with _sp2() as pw2:
                b2 = pw2.chromium.connect_over_cdp(get_cdp_ws_url())
                ctx2 = b2.contexts[0] if b2.contexts else b2.new_context()
                p2 = ctx2.new_page()
                try:
                    try:
                        p2.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
                    except Exception:
                        pass
                    time.sleep(1)
                    new_candidates = _fetch_abstracts_batch(p2, new_candidates)
                finally:
                    p2.close()
        except Exception as e:
            print(f"[warn] abstract 获取失败: {e}", flush=True)

    return new_candidates


def download_by_dois(dois: list[str]) -> list[str]:
    """仅下载指定 DOI 列表的 PDF。返回下载成功的 DOI 列表。"""
    if not dois:
        return []

    # 去重：跳过 vault 已有 DOI
    print("[dedup] 读取 vault DOI 索引...", flush=True)
    existing_dois = build_vault_doi_index()
    new_dois = [d for d in dois if d not in existing_dois]
    skipped = len(dois) - len(new_dois)
    if skipped:
        print(f"[dedup] 跳过 {skipped} 篇已入库，下载 {len(new_dois)} 篇", flush=True)
    if not new_dois:
        print("[done ] 全部已有，无需下载")
        return []

    if not check_cdp_port():
        print("[error] Chrome 未以调试模式启动。")
        sys.exit(1)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[error] playwright 未安装")
        sys.exit(1)

    downloaded = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            try:
                page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            # auth check
            warm_webvpn_session(page)
            auth_ok = check_auth(page)
            if not auth_ok:
                print("[auth ] 直连认证失败，尝试 scidownload 入口...", flush=True)
                auth_ok = try_scidownload_fallback(page)
            if not auth_ok:
                auth_alert("下载前认证检查失败")
                return []

            for doi in new_dois:
                paper = _lookup_paper_info(page, doi)
                topic = categorize(paper["title"]) if paper.get("title") else "Others"
                time.sleep(2)
                ok = download_paper(page, paper, topic)
                if ok:
                    downloaded.append(doi)
                else:
                    # auth fail → try recover once
                    try:
                        page.goto(XPLORE_HOME, wait_until="commit", timeout=15000)
                        time.sleep(2)
                    except Exception:
                        pass
                    if check_auth(page):
                        ok = download_paper(page, paper, topic)
                        if ok:
                            downloaded.append(doi)
        finally:
            page.close()

    print(f"\n[done ] 下载完成：{len(downloaded)}/{len(dois)} 篇")
    return downloaded


def _lookup_paper_info(page, doi: str) -> dict:
    """通过 DOI 查询论文的 title/year 等基本信息（用搜索 API）。"""
    import json as _json
    try:
        info = page.evaluate(f"""
        async () => {{
            const resp = await fetch('/rest/search', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    queryText: '{doi}',
                    rowsPerPage: 1,
                    newsearch: true
                }})
            }});
            const data = await resp.json();
            const r = data.records?.[0] || {{}};
            return {{
                title: r.articleTitle || '',
                year: r.publicationYear || 0,
                pubtitle: r.publicationTitle || '',
            }};
        }}
        """)
        title = (info.get("title") or "").strip()
        year = int(info.get("year", 0) or 0)
        return {
            "doi": doi,
            "title": title or doi,
            "year": year,
            "cited_by": 0,
            "url": f"{XPLORE_HOME}/document/{doi}",
        }
    except Exception:
        return {"doi": doi, "title": doi, "year": 0, "cited_by": 0, "url": ""}


def main():
    parser = argparse.ArgumentParser(description="IEEE Xplore 搜索下载")
    parser.add_argument("query", nargs="*", help="搜索词（--doi 模式下可省略）")
    parser.add_argument("--max", type=int, default=10, help="下载篇数（默认 10）")
    parser.add_argument("--dry-run", action="store_true", help="仅列出候选，不下载")
    parser.add_argument("--search-only", action="store_true",
                        help="仅搜索返回候选列表（JSON），不下载")
    parser.add_argument("--abstracts", action="store_true",
                        help="同时获取摘要（与 --search-only 配合）")
    parser.add_argument("--doi", nargs="*", default=None,
                        help="下载指定 DOI 列表（跳过搜索）")
    args = parser.parse_args()

    # ── 模式 1：仅搜索 ──
    if args.search_only:
        query = " ".join(args.query)
        # 把所有 log print 重定向到 stderr，stdout 只输出纯 JSON
        # 这样 cad_tools._run 的 json.loads(stdout) 能成功解析
        import io as _io
        _real_stdout = sys.stdout
        sys.stdout = sys.stderr          # log → stderr
        try:
            candidates = search_candidates(query, fetch_abstracts=args.abstracts)
        finally:
            sys.stdout = _real_stdout    # restore
        import json as _json
        # 输出纯 JSON 数组，key 格式与 step6_ieee 期望的 "papers" 对齐
        out = _json.dumps({"papers": candidates}, ensure_ascii=False)
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.buffer.flush()
        return

    # ── 模式 2：仅下载指定 DOI ──
    if args.doi is not None:
        if not args.doi:
            # 从 stdin 读取 DOI JSON 列表
            import json as _json
            data = _json.loads(sys.stdin.read())
            args.doi = data if isinstance(data, list) else data.get("dois", [])
        # 把 log 重定向到 stderr，stdout 只输出纯 JSON（供 cad_tools._run 解析）
        _real_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            downloaded = download_by_dois(args.doi)
        finally:
            sys.stdout = _real_stdout
        import json as _json
        out = _json.dumps(
            {"new_papers": [{"doi": d} for d in downloaded]},
            ensure_ascii=False,
        )
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.buffer.flush()
        return

    # ── 模式 3：全自动（默认）──
    query = " ".join(args.query)
    dois = search_and_download(query, max_papers=args.max, dry_run=args.dry_run)
    if dois:
        print("下载的 DOI：", dois)


if __name__ == "__main__":
    main()
