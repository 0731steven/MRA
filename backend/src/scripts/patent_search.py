#!/usr/bin/env python3
"""Google Patents 搜索下载脚本。

前置条件：pip install playwright && playwright install chromium
Chrome CDP 自动启动（无需手动运行 launch 脚本）。

用法:
  python patent_search.py "Class-D amplifier dead time"            # 搜索 + 下载
  python patent_search.py "SAR ADC switching" --max 5               # 最多 5 篇
  python patent_search.py "dToF SPAD" --search-only                 # 仅搜索，不下载
  python patent_search.py "buck converter" --status APPLICATION     # 搜索申请中专利
"""

import argparse
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _cdp_helper import ensure_cdp, check_cdp_port, get_cdp_ws_url
from _patent_index import load_index, add_to_index, get_patent_numbers, PATENT_SRC

PATENTS_HOME = "https://patents.google.com"
INBOX = PATENT_SRC / "inbox"

# IPC prefix → 目录名（Google Patents 返回 H03F3/45 → 映射到 H03F-信号链与放大器）
# 默认映射：常用 IPC 前缀 → 目录名（即使本地目录尚不存在也能自动 mkdir）
_DEFAULT_IPC_MAP: dict[str, str] = {
    "H03F": "H03F-信号链与放大器",
    "H03M": "H03M-数据转换器",
    "H03K": "H03K-脉冲与数字电路",
    "H03L": "H03L-锁相环与频率合成",
    "H03D": "H03D-解调与频率变换",
    "H02M": "H02M-电力转换",
    "H01L": "H01L-半导体器件",
    "H04B": "H04B-传输与通信",
    "H04L": "H04L-数字传输",
    "G01S": "G01S-测距与雷达",
    "G01R": "G01R-测量与测试",
    "G04F": "G04F-时间测量",
    "G06F": "G06F-数字计算",
}

IPC_DIR_MAP: dict[str, str] = dict(_DEFAULT_IPC_MAP)
# 扫描本地已有目录，覆盖/补充默认映射
if PATENT_SRC.exists():
    for d in PATENT_SRC.iterdir():
        if d.is_dir() and "-" in d.name:
            prefix = d.name.split("-")[0]
            IPC_DIR_MAP[prefix] = d.name


# 标题关键词 → 目录名（当 IPC 为空时的 fallback，与 patent_search_cnipa.py 保持同步）
_TITLE_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["LDO", "dropout regulator", "low-dropout", "PSRR", "linear regulator"], "H02M-电力转换"),
    (["DC-DC", "buck converter", "boost converter", "switching regulator",
      "charge pump", "voltage converter", "power converter", "DCDC"], "H02M-电力转换"),
    (["Class-D", "Class D", "audio amplifier", "power amplifier", "PA ", " PA,"], "H03F-信号链与放大器"),
    (["LNA", "op-amp", "operational amplifier", "comparator", "transimpedance"], "H03F-信号链与放大器"),
    (["ADC", "DAC", "analog-to-digital", "digital-to-analog", "SAR ADC",
      "sigma-delta", "delta-sigma", "pipelined ADC"], "H03M-数据转换器"),
    (["PLL", "phase-locked loop", "VCO", "oscillator", "clock generator",
      "frequency synthesizer", "DLL"], "H03L-锁相环与频率合成"),
    (["MEMS", "gyroscope", "accelerometer", "inertial sensor",
      "resonator", "micromachined"], "B81-MEMS"),
    (["LiDAR", "ToF", "SPAD", "time-of-flight", "photodetector",
      "photon counting", "avalanche"], "G01-传感器与测量"),
    (["radar", "FMCW", "distance measurement", "ranging"], "G01S-测距与雷达"),
    (["transistor", "MOSFET", "FinFET", "GaN", "SiC", "semiconductor device",
      "gate driver", "power device"], "H01L-半导体器件与工艺"),
    (["RF", "transceiver", "wireless", "5G", "antenna", "mmWave",
      "Bluetooth", "WiFi"], "H04-通信与射频"),
    (["memory", "SRAM", "DRAM", "Flash", "storage"], "G11C-存储器"),
    (["display", "LCD", "OLED", "pixel driver"], "G09G-显示"),
    (["battery", "charger", "charging", "energy harvesting", "PMU",
      "power management"], "H02J-电源管理与充电"),
    (["packaging", "interconnect", "PCB", "substrate", "through-silicon via",
      "TSV", "flip-chip"], "H05K-封装与互连"),
    (["automotive", "ADAS", "vehicle", "in-vehicle"], "B60-汽车电子"),
]


def classify_by_title(title: str) -> str | None:
    """根据专利标题关键词猜 IPC 目录（IPC 为空时的 fallback）。"""
    title_lower = title.lower()
    for keywords, dirname in _TITLE_KEYWORD_MAP:
        if any(kw.lower() in title_lower for kw in keywords):
            target = PATENT_SRC / dirname
            target.mkdir(parents=True, exist_ok=True)
            return dirname
    return None


def classify_by_ipc(patent: dict) -> str | None:
    """根据专利 IPC 前缀匹配本地目录，返回目录名或 None（去 inbox）。"""
    ipc_code = patent.get("ipc", "")
    title = patent.get("title", "")
    if not ipc_code:
        # IPC 为空：用标题关键词兜底
        result = classify_by_title(title)
        if result:
            print(f"  [ipc ] IPC 为空，按标题分类 → {result}", flush=True)
        return result
    # 提取 IPC section: H03F3/45 → H03F
    ipc_prefix = ipc_code.split("/")[0].rstrip("0123456789")[:4]
    if ipc_prefix in IPC_DIR_MAP:
        # 自动创建目录（默认映射可能本地尚无对应目录）
        target_dir = PATENT_SRC / IPC_DIR_MAP[ipc_prefix]
        target_dir.mkdir(parents=True, exist_ok=True)
        return IPC_DIR_MAP[ipc_prefix]
    # 兜底：尝试前 4 字符匹配
    for prefix, dname in IPC_DIR_MAP.items():
        if ipc_prefix.startswith(prefix) or prefix.startswith(ipc_prefix):
            return dname
    # IPC 有值但无匹配目录：也尝试标题兜底
    result = classify_by_title(title)
    if result:
        print(f"  [ipc ] IPC '{ipc_prefix}' 无匹配目录，按标题分类 → {result}", flush=True)
    return result


def rewrite_query(academic_query: str) -> str:
    """将学术关键词改写为专利功能描述词。

    专利更偏重功能/结构描述，而非学术术语。
    简单启发式：保留核心术语，去掉论文式短语。
    """
    # 保留原 query，由 LLM 在 research-papers skill 中改写
    # 此处仅做基础清理
    removals = ["paper", "survey", "review", "comparison", "state of the art",
                "novel", "high performance", "low power"]
    q = academic_query
    for r in removals:
        q = re.sub(rf"\b{r}\b", "", q, flags=re.IGNORECASE)
    return " ".join(q.split())


def search_patents(page, query: str, max_results: int = 5,
                   status: str = "GRANT", _out=None) -> list[dict]:
    """搜索 Google Patents，返回专利列表。"""
    if _out is None:
        _out = sys.stdout
    import urllib.parse
    query_encoded = urllib.parse.quote(query)
    status_map = {"GRANT": "GRANT", "APPLICATION": "APPLICATION"}
    status_val = status_map.get(status.upper(), "GRANT")
    search_url = f"{PATENTS_HOME}/?q={query_encoded}&status={status_val}&language=ENGLISH"

    print(f"[search] {search_url}", file=_out, flush=True)
    page.goto(search_url, wait_until="commit", timeout=30000)
    try:
        page.wait_for_selector("search-result-item", timeout=12000)
    except Exception:
        pass  # 超时说明可能被拦截，继续让诊断输出揭示原因

    # 诊断：输出页面前500字符，判断是否被拦截或DOM未渲染
    try:
        _snippet = page.evaluate("() => document.body.innerHTML.substring(0, 500)")
        print(f"[debug] DOM snippet: {_snippet!r}", file=_out, flush=True)
        _item_count = page.evaluate("() => document.querySelectorAll('search-result-item, article').length")
        print(f"[debug] search-result-item count: {_item_count}", file=_out, flush=True)
    except Exception as _dbg_e:
        print(f"[debug] 诊断失败: {_dbg_e}", file=_out, flush=True)

    # 解析搜索结果
    patents = page.evaluate(r"""
    () => {
        const results = [];
        const items = document.querySelectorAll('search-result-item, article');
        items.forEach(item => {
            const titleEl = item.querySelector('h3');
            const assigneeEl = item.querySelector('.assignee, [itemprop="assignee"]');
            const abstractEl = item.querySelector('.abstract, .snippet, [itemprop="description"]');
            const dateEl = item.querySelector('time, .date, [itemprop="datePublished"]');

            // Google Patents 2024+ HTML: patent number embedded in image URLs
            // Format: .../US09236841-20160112-D00000.png → extract US + digits, strip leading zeros
            let patentNum = '';
            const imgs = item.querySelectorAll('img[src*="patentimages"]');
            for (const img of imgs) {
                const src = img.getAttribute('src') || '';
                const m = src.match(/\/([A-Z]{2})0*(\d{5,})/);
                if (m) { patentNum = m[1] + m[2]; break; }
            }

            // Fallback: scan item textContent for patent number pattern
            if (!patentNum) {
                const text = item.textContent || '';
                const pm = text.match(/\b([A-Z]{2}\d{5,12}[A-Z]?\d?)\b/);
                if (pm) patentNum = pm[1];
            }

            if (titleEl && patentNum) {
                // Extract IPC from item text (e.g., "H03F 3/217")
                const text = item.textContent || '';
                const ipcMatch = text.match(/([A-H]\d{2}[A-Z]?\s*\d{1,2}\/\d{2,})/);
                results.push({
                    patent_number: patentNum,
                    title: titleEl.textContent.trim().substring(0, 200),
                    assignee: assigneeEl ? assigneeEl.textContent.trim() : '',
                    abstract: abstractEl ? abstractEl.textContent.trim().substring(0, 500) : '',
                    filing_date: dateEl ? dateEl.getAttribute('datetime') || dateEl.textContent.trim() : '',
                    url: 'https://patents.google.com/patent/' + patentNum + '/en',
                    ipc: ipcMatch ? ipcMatch[1].replace(/\\s+/g, '') : ''
                });
            }
        });
        return results;
    }
    """)

    # 去重（按 patent_number）
    seen = set()
    unique = []
    for p in patents:
        pn = p.get("patent_number", "")
        if pn and pn not in seen:
            seen.add(pn)
            unique.append(p)
        if len(unique) >= max_results:
            break

    return unique


def _scrape_pdf_url_from_page(page) -> str | None:
    """从专利页面提取真实 PDF URL，支持多种 fallback 策略。"""
    import urllib.request as _urllib
    import urllib.error

    # Strategy 1: scan page HTML for pre-rendered patentimages PDF links (EP patents)
    try:
        urls = page.evaluate("""
        () => {
            const urls = [];
            const links = document.querySelectorAll('a[href*=".pdf"]');
            links.forEach(a => {
                const href = a.getAttribute('href');
                if (href && href.includes('patentimages.storage.googleapis.com')) {
                    urls.push(href);
                }
            });
            if (urls.length === 0) {
                const html = document.documentElement.outerHTML;
                const re = /https:\\/\\/patentimages\\.storage\\.googleapis\\.com\\/[^"\\s]+\\.pdf/g;
                const matches = html.match(re);
                if (matches) urls.push(...matches);
            }
            return urls;
        }
        """)
        if urls:
            return urls[0]
    except Exception:
        pass

    # Strategy 2: try direct patentimages URL construction (common patterns for US/CN grants)
    try:
        import urllib.error as _urllib_error
        current_url = page.url  # e.g. https://patents.google.com/patent/US10234567/en
        m = re.search(r'/patent/([A-Z]{2}\d+[A-Z]?\d*)/en', current_url)
        if m:
            pn = m.group(1)
            candidates = [
                f"https://patentimages.storage.googleapis.com/pdfs/{pn}.pdf",
                f"https://patentimages.storage.googleapis.com/{pn[0]}/{pn[1]}/{pn[2]}/{pn}.pdf",
            ]
            for candidate_url in candidates:
                try:
                    req = _urllib.Request(candidate_url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
                    with _urllib.urlopen(req, timeout=10) as resp:
                        if resp.status == 200 and "pdf" in resp.headers.get("Content-Type", "").lower():
                            return candidate_url
                except (_urllib_error.HTTPError, _urllib_error.URLError, Exception):
                    continue
    except Exception:
        pass

    # Strategy 3: navigate to ?output=pdf and capture redirect destination via response interception
    try:
        current_url = page.url
        m = re.search(r'/patent/([A-Z]{2}\d+[A-Z]?\d*)/en', current_url)
        if m:
            pn = m.group(1)
            captured = []

            def on_response(response):
                url = response.url
                if ".pdf" in url and "patentimages" in url and response.status < 400:
                    captured.append(url)

            page.on("response", on_response)
            try:
                page.goto(f"https://patents.google.com/patent/{pn}/en?output=pdf",
                          wait_until="commit", timeout=15000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
            finally:
                page.remove_listener("response", on_response)

            if captured:
                return captured[0]

            # Also check if page itself is now a PDF URL
            if ".pdf" in page.url and "patentimages" in page.url:
                return page.url
    except Exception:
        pass

    return None


def download_patent(page, patent: dict, output_dir: str = "", stderr: bool = False) -> bool:
    """下载专利 PDF。stderr=True 时进度输出到 stderr（流水线 --patent-numbers 模式用）。"""
    _out = sys.stderr if stderr else sys.stdout
    pn = patent.get("patent_number", "")
    if not pn:
        return False

    assignee = patent.get("assignee", "Unknown").strip()
    title = patent.get("title", "No Title")
    safe_title = re.sub(r'[<>:"|?*\\/]', '', title[:60]).strip()

    filename = f"{pn} - [{assignee}] {safe_title}.pdf"

    if output_dir:
        dest_dir = pathlib.Path(output_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        ipc_dir = None
    else:
        ipc_dir = classify_by_ipc(patent)
        dest_dir = PATENT_SRC / ipc_dir if ipc_dir else INBOX
        dest_dir.mkdir(parents=True, exist_ok=True)
    save_path = dest_dir / filename

    label = ipc_dir or (output_dir or "inbox")
    print(f"  [dl  ] {pn} → {label} ({assignee})", file=_out, flush=True)

    patent_page_url = f"{PATENTS_HOME}/patent/{pn}/en"

    try:
        page.goto(patent_page_url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(2000)

        pdf_url = _scrape_pdf_url_from_page(page)
        if not pdf_url:
            print(f"  [fail] 未找到 PDF 下载链接", file=_out, flush=True)
            return False

        print(f"  [pdf ] {pdf_url[:80]}...", file=_out, flush=True)

        import urllib.request as _urllib
        req = _urllib.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with _urllib.urlopen(req, timeout=60) as resp:
                body = resp.read()
        except Exception as dl_err:
            print(f"  [fail] 直接下载失败: {dl_err}", file=_out, flush=True)
            return False

    except Exception as e:
        print(f"  [warn] 下载异常: {type(e).__name__}: {str(e)[:60]}", file=_out, flush=True)
        return False

    if body and body.startswith(b'%PDF-'):
        save_path.write_bytes(body)
        if not output_dir:
            add_to_index(pn, ipc_dir or "inbox")
        print(f"  [ok  ] 已保存 {save_path.name} ({len(body)//1024}KB)", file=_out, flush=True)
        return True
    else:
        print(f"  [fail] 非 PDF 响应 ({len(body)} bytes)", file=_out, flush=True)
        return False


def search_only(query: str, max_papers: int = 5, status: str = "GRANT",
                json_mode: bool = False) -> list[dict]:
    """仅搜索，不下载。返回专利列表。json_mode=True 时将结果以 JSON 输出到 stdout，进度输出到 stderr。"""
    import json as _json
    _p = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if json_mode else print

    if not ensure_cdp():
        _p("[error] 无法启动研究 Chrome")
        sys.exit(1)

    _p("[dedup] 读取专利索引...", flush=True)
    existing = get_patent_numbers()
    _p(f"[dedup] 本地已有 {len(existing)} 篇专利", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _p("[error] playwright 未安装")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            try:
                page.goto(PATENTS_HOME, wait_until="commit", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            results = search_patents(page, query, max_results=max_papers * 2, status=status,
                                     _out=sys.stderr if json_mode else sys.stdout)
            new_results = [p for p in results if p.get("patent_number", "") not in existing]
        finally:
            page.close()

    _p(f"[dedup] 过滤后 {len(new_results)} 篇新专利（跳过 {len(results) - len(new_results)} 篇已有）",
       flush=True)
    new_results = new_results[:max_papers]

    if json_mode:
        sys.stdout.buffer.write((_json.dumps({"patents": new_results}, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    return new_results


def run_patent_numbers(patent_numbers: list[str], output_dir: str = "",
                       dry_run: bool = False) -> list[str]:
    """按指定专利号批量下载，用于两段式流水线的精选下载阶段。进度输出到 stderr，JSON 结果输出到 stdout。"""
    _e = lambda *a, **k: print(*a, file=sys.stderr, **k)

    if not ensure_cdp():
        _e("[error] 无法启动研究 Chrome", flush=True)
        sys.exit(1)

    existing = get_patent_numbers()
    to_download = [n for n in patent_numbers if n not in existing]
    skipped = [n for n in patent_numbers if n in existing]
    if skipped:
        _e(f"[dedup] 跳过 {len(skipped)} 篇已有：{', '.join(skipped)}", flush=True)
    if not to_download:
        _e("[done ] 所有指定专利已在本地", flush=True)
        sys.stdout.buffer.write(b'{"downloaded": []}\n')
        sys.stdout.buffer.flush()
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _e("[error] playwright 未安装")
        sys.exit(1)

    downloaded = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            for pn in to_download:
                if dry_run:
                    _e(f"  [dry ] {pn}", flush=True)
                    continue
                patent = {"patent_number": pn, "title": pn, "assignee": "", "ipc": ""}
                ok = download_patent(page, patent, output_dir=output_dir, stderr=True)
                if ok:
                    downloaded.append(pn)
                time.sleep(1)
        finally:
            page.close()

    _e(f"[done ] 下载完成：{len(downloaded)} 篇", flush=True)
    import json as _json
    sys.stdout.buffer.write((_json.dumps({"downloaded": downloaded}, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    return downloaded


def run(query: str, max_papers: int = 5, dry_run: bool = False,
        search_only_flag: bool = False, status: str = "GRANT",
        output_dir: str = "", json_mode: bool = False) -> list[str]:
    """主流程：搜索 → 下载，返回下载成功的专利号列表。"""
    if search_only_flag:
        search_only(query, max_papers, status, json_mode=json_mode)
        return []

    if not ensure_cdp():
        print("[error] 无法启动研究 Chrome")
        sys.exit(1)

    print("[dedup] 读取专利索引...", flush=True)
    existing = get_patent_numbers()
    print(f"[dedup] 本地已有 {len(existing)} 篇专利", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[error] playwright 未安装")
        sys.exit(1)

    query = rewrite_query(query)
    print(f"[query] {query}", flush=True)

    downloaded = []

    with sync_playwright() as pw:
        ws = get_cdp_ws_url()
        print(f"[cdp  ] 连接 {ws}...", flush=True)
        browser = pw.chromium.connect_over_cdp(ws)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            try:
                page.goto(PATENTS_HOME, wait_until="commit", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            results = search_patents(page, query, max_results=max_papers * 2, status=status)
            new_results = [p for p in results if p.get("patent_number", "") not in existing]
            skipped = len(results) - len(new_results)
            print(f"[found] {len(results)} 篇（跳过 {skipped} 篇已有，剩余 {len(new_results)} 篇新）",
                  flush=True)
            new_results = new_results[:max_papers]

            for i, patent in enumerate(new_results):
                print(f"\n[{i+1}/{len(new_results)}] {patent.get('title', '')[:60]}", flush=True)
                if dry_run:
                    print(f"  [dry ] {patent.get('patent_number', '?')}", flush=True)
                    continue
                time.sleep(2)
                ok = download_patent(page, patent, output_dir=output_dir)
                if ok:
                    downloaded.append(patent.get("patent_number", ""))
        finally:
            page.close()

    print(f"\n[done ] 下载完成：{len(downloaded)} 篇", flush=True)
    if downloaded:
        print("[next ] 运行 patent_convert.py 转换新专利", flush=True)
    return downloaded


def main():
    parser = argparse.ArgumentParser(
        description="Google Patents 搜索下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python patent_search.py "Class-D amplifier dead time"
  python patent_search.py "SAR ADC switching" --max 5
  python patent_search.py "dToF SPAD" --search-only
  python patent_search.py "dToF SPAD" --search-only --json
  python patent_search.py "buck converter" --status APPLICATION
  python patent_search.py --patent-numbers US11234567 US11345678 --output-dir staging/task_1/patent/
        """
    )
    parser.add_argument("query", nargs="*", help="搜索关键词（与 --patent-numbers 二选一）")
    parser.add_argument("--patent-numbers", nargs="+", metavar="PN",
                        help="直接指定专利号批量下载，无需搜索（两段式评分后精选下载用）")
    parser.add_argument("--max", type=int, default=10, help="最大下载数 (default: 10)")
    parser.add_argument("--search-only", action="store_true", help="仅搜索，不下载")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="--search-only 时将结果以 JSON 输出到 stdout（供流水线解析）")
    parser.add_argument("--dry-run", action="store_true", help="列出但不下载")
    parser.add_argument("--output-dir", type=str, default="",
                        help="下载输出目录（默认按 IPC 自动分类到 PATENT_PDF_SRC）")
    parser.add_argument("--status", type=str, default="GRANT",
                        choices=["GRANT", "APPLICATION"],
                        help="专利状态 (default: GRANT)")
    args = parser.parse_args()

    if args.patent_numbers:
        run_patent_numbers(args.patent_numbers, output_dir=args.output_dir, dry_run=args.dry_run)
    elif args.query:
        query = " ".join(args.query)
        run(query, max_papers=args.max, dry_run=args.dry_run,
            search_only_flag=args.search_only, status=args.status,
            output_dir=args.output_dir, json_mode=args.json_mode)
    else:
        parser.error("请提供搜索关键词，或使用 --patent-numbers 指定专利号")


if __name__ == "__main__":
    main()
