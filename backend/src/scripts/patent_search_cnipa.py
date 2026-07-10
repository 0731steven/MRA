#!/usr/bin/env python3
"""CNIPA 专利检索及分析系统 搜索下载脚本。

Chrome CDP 驱动，国内直连，零翻墙。
- 搜索：Playwright CDP 操作 CNIPA 常规检索页
- 详情/下载：websocket 直连 detail tab（绕过 Playwright 新 tab 不可见限制）
- 下载：Foxit PDF viewer iframe 内 #download 按钮

定位：Google Patents 首选 fallback（大陆稳定）。

前置条件：
- Chrome CDP 已运行（launch_research_chrome.sh，含 --remote-allow-origins=*）
- CNIPA 需登录账号（在研究 Chrome 中手动登录一次，session 持久化）
- pip install websocket-client

用法:
  python patent_search_cnipa.py "buck converter"
  python patent_search_cnipa.py "SAR ADC switching" --max 5
  python patent_search_cnipa.py "dToF SPAD" --search-only
  python patent_search_cnipa.py "buck converter" --dry-run
  python patent_search_cnipa.py "buck converter" --country US    # 默认 US
  python patent_search_cnipa.py "降压转换器" --country CN        # 中国专利
"""

import argparse
import json
import pathlib
import re
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _cdp_helper import ensure_cdp, get_cdp_ws_url
from _patent_index import load_index, add_to_index, get_patent_numbers, PATENT_SRC

CNIPA_URL = "https://pss-system.cponline.cnipa.gov.cn"
CNIPA_SEARCH = f"{CNIPA_URL}/conventionalSearch"
import os as _os
CDP_JSON = f"http://localhost:{_os.environ.get('CDP_PORT', '9222')}/json"
DL_DIR = pathlib.Path.home() / "Downloads"
INBOX = PATENT_SRC / "inbox"

# IPC prefix → 目录名
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
if PATENT_SRC.exists():
    for d in PATENT_SRC.iterdir():
        if d.is_dir() and "-" in d.name:
            prefix = d.name.split("-")[0]
            IPC_DIR_MAP[prefix] = d.name


# 标题关键词 → 目录名（当 IPC 为空时的 fallback）
# 关键词不区分大小写，按顺序匹配，第一个命中即用
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
            # 检查目录是否在 vault 中存在，不存在则建
            target = PATENT_SRC / dirname
            target.mkdir(parents=True, exist_ok=True)
            return dirname
    return None


def classify_by_ipc(patent: dict) -> str | None:
    ipc_code = patent.get("ipc", "")
    title = patent.get("title", "")
    if not ipc_code:
        # IPC 为空：用标题关键词兜底
        result = classify_by_title(title)
        if result:
            print(f"  [ipc ] IPC 为空，按标题分类 → {result}", flush=True)
        return result
    first_ipc = ipc_code.split(";")[0].strip()
    ipc_prefix = first_ipc.split("/")[0].rstrip("0123456789")[:4]
    if ipc_prefix in IPC_DIR_MAP:
        target_dir = PATENT_SRC / IPC_DIR_MAP[ipc_prefix]
        target_dir.mkdir(parents=True, exist_ok=True)
        return IPC_DIR_MAP[ipc_prefix]
    for prefix, dname in IPC_DIR_MAP.items():
        if ipc_prefix.startswith(prefix) or prefix.startswith(ipc_prefix):
            return dname
    # IPC 有值但无匹配目录：也尝试标题兜底
    result = classify_by_title(title)
    if result:
        print(f"  [ipc ] IPC '{ipc_prefix}' 无匹配目录，按标题分类 → {result}", flush=True)
    return result


# ─── Websocket CDP helper ────────────────────────────────────────────────

class _CdpTab:
    """通过 websocket 直连 Chrome tab 执行 CDP 命令。"""

    def __init__(self, ws_url: str):
        import websocket as _ws
        self.ws = _ws.create_connection(ws_url, timeout=30)
        self._mid = 1
        self.send("Runtime.enable")

    def send(self, method: str, params: dict | None = None) -> dict:
        msg = {"id": self._mid, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))
        self._mid += 1
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self._mid - 1:
                return r.get("result", {})

    def js(self, expr: str) -> str:
        r = self.send("Runtime.evaluate", {"expression": expr})
        return r.get("result", {}).get("value", "")

    def mouse_click(self, x: float, y: float) -> None:
        """CDP Input.dispatchMouseEvent 真实鼠标点击。"""
        self.send("Input.dispatchMouseEvent",
                  {"type": "mousePressed", "x": x, "y": y,
                   "button": "left", "clickCount": 1})
        self.send("Input.dispatchMouseEvent",
                  {"type": "mouseReleased", "x": x, "y": y,
                   "button": "left", "clickCount": 1})

    def click_iframe_button(self, btn_id: str) -> bool:
        """通过 CDP 鼠标点击 iframe 内按钮（JS .click() 无效）。"""
        coords = self.js(f"""
        (() => {{
            const f = document.querySelector('iframe');
            if (!f || !f.contentDocument) return 'none';
            const btn = f.contentDocument.getElementById('{btn_id}');
            if (!btn) return 'none';
            const r = btn.getBoundingClientRect();
            const ir = f.getBoundingClientRect();
            return JSON.stringify({{x: ir.x + r.x + r.width/2, y: ir.y + r.y + r.height/2}});
        }})()
        """)
        if coords == "none":
            return False
        c = json.loads(coords)
        self.mouse_click(c["x"], c["y"])
        return True

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _find_detail_tab_ws(timeout: int = 10) -> str | None:
    """轮询 /json 找 detail tab 的 websocket URL。"""
    for _ in range(timeout * 2):
        try:
            resp = urllib.request.urlopen(CDP_JSON, timeout=5)
            for p in json.loads(resp.read()):
                if "documents/detail" in p.get("url", ""):
                    return p.get("webSocketDebuggerUrl", "")
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _close_detail_tabs() -> None:
    """关闭所有已打开的 detail tab（通过 CDP Page.close）。"""
    try:
        resp = urllib.request.urlopen(CDP_JSON, timeout=5)
        for p in json.loads(resp.read()):
            if "documents/detail" in p.get("url", ""):
                ws_url = p.get("webSocketDebuggerUrl", "")
                if ws_url:
                    try:
                        tab = _CdpTab(ws_url)
                        tab.send("Page.close")
                        tab.close()
                    except Exception:
                        pass
    except Exception:
        pass


# ─── Playwright 搜索部分 ──────────────────────────────────────────────────

def _accept_disclaimer(page) -> None:
    try:
        if "Disclaimer" in page.url or "免责" in page.title():
            page.click("button:has-text('同意')", timeout=5000)
            time.sleep(2)
    except Exception:
        pass


def _select_country(page, country: str = "US") -> None:
    country_map = {
        "US": "美国", "CN": "中国", "EP": "EPO", "JP": "日本",
        "KR": "韩国", "DE": "德国", "GB": "英国", "FR": "法国",
        "CH": "瑞士", "WO": "WIPO",
    }
    label = country_map.get(country.upper(), country)
    try:
        page.locator(".selectTitle").click(timeout=5000)
        time.sleep(1)
        page.locator(f".el-checkbox:has-text('{label}') .el-checkbox__inner").click(timeout=5000)
        time.sleep(0.3)
        page.locator(".selectTitle").click(timeout=3000)
        time.sleep(0.5)
    except Exception:
        print(f"[warn] 选国家失败: {label}", flush=True)


def _do_search(page, query: str) -> None:
    try:
        inp = page.locator("input.input")
        inp.wait_for(state="visible", timeout=10000)
        inp.click()
        time.sleep(0.3)
        inp.fill("")
        inp.type(query, delay=30)
        time.sleep(0.5)
        page.locator(".inputBox .btn").click(timeout=5000)
        time.sleep(1)
    except Exception as e:
        print(f"[error] 搜索操作失败: {e}", flush=True)


def _find_result_page(context, timeout: int = 45):
    for _ in range(timeout * 2):
        for p in context.pages:
            if "retrieveList" in p.url:
                time.sleep(2)
                return p
        time.sleep(0.5)
    return None


def _goto_next_page(result_page) -> bool:
    """点击下一页，成功返回 True，无下一页返回 False。"""
    try:
        next_btn = result_page.locator(".el-pagination button:has-text('>')").first
        if not next_btn.is_visible(timeout=2000):
            next_btn = result_page.locator("button.btn-next").first
        if next_btn.is_enabled():
            next_btn.click(timeout=3000)
            time.sleep(3)
            return True
    except Exception:
        pass
    return False


def _parse_result_list(result_page) -> list[dict]:
    return result_page.evaluate("""
    () => {
        const items = [];
        const text = document.body.innerText;
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l);
        let current = null;
        for (let i = 0; i < lines.length; i++) {
            const l = lines[i];
            if (/^(US|EP|CN|WO|JP|KR|DE|GB|FR)\\d{5,}[A-Z]\\d?$/.test(l)) {
                if (current && current.patent_number) items.push(current);
                current = { patent_number: l, app_number: '', filing_date: '', title: '', assignee: '', abstract: '', ipc: '' };
            } else if (current) {
                if (/^(US|EP|CN|WO)\\d{10,}$/.test(l) && !current.app_number) {
                    current.app_number = l;
                } else if (/^\\d{4}\\.\\d{2}\\.\\d{2}$/.test(l) && !current.filing_date) {
                    current.filing_date = l.replace(/\\./g, '-');
                } else if (!current.title && l.length > 10 && l === l.toUpperCase()
                           && !/^(摘要|著录|IPC|CPC|法律|同族|引证|被引证|主权利|详览|收藏)/.test(l)) {
                    current.title = l;
                } else if (current.title && !current.assignee && l.length > 2
                           && l === l.toUpperCase()
                           && !/^(摘要|著录|IPC|CPC|法律|同族|引证|被引证|主权利|详览|收藏)/.test(l)) {
                    current.assignee = l;
                }
            }
        }
        if (current && current.patent_number) items.push(current);
        return items;
    }
    """)


def _get_total_count(result_page) -> int:
    text = result_page.evaluate("() => document.body?.innerText || ''")
    m = re.search(r'(\d+)\s*条数据', text)
    return int(m.group(1)) if m else 0


# ─── detail tab 操作 ──────────────────────────────────────────────────────

def _open_detail(result_page, pn: str) -> _CdpTab | None:
    """点专利号链接 → 等 detail tab 出现 → 等页面加载 → 返回 CdpTab 或 None。"""
    # 先关已有 detail tab
    _close_detail_tabs()
    time.sleep(0.5)

    # 点专利号链接
    try:
        result_page.locator(f"text={pn}").first.click(timeout=5000)
    except Exception:
        result_page.evaluate(f"""
        () => {{
            const all = document.querySelectorAll('a, span');
            for (const el of all) {{
                if (el.textContent?.trim() === '{pn}' && el.offsetWidth > 0) {{
                    el.click(); return;
                }}
            }}
        }}
        """)

    time.sleep(3)

    ws_url = _find_detail_tab_ws(timeout=10)
    if not ws_url:
        return None

    try:
        tab = _CdpTab(ws_url)
        # 等页面加载
        tab.js("""
        (() => {
            return new Promise(resolve => {
                if (document.readyState === 'complete') { resolve('loaded'); return; }
                window.addEventListener('load', () => resolve('loaded'));
                setTimeout(() => resolve('timeout'), 15000);
            });
        })()
        """)
        time.sleep(2)

        # ⚠️ CDP 必须显式启用下载行为，否则点击下载不写文件
        dl_path = str(DL_DIR.absolute())
        tab.send("Page.enable")
        tab.send("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": dl_path,
            "eventsEnabled": True
        })

        return tab
    except Exception:
        return None


def _read_and_download(result_page, patent: dict, download: bool = False) -> str | None:
    """点专利号 → ws 连 detail → 读著录 → [可选]全文图像下载 → 关 tab。

    合并著录读取和 PDF 下载为一次 detail tab 操作，
    避免关 tab 后重新打开时结果页状态丢失。

    返回 PDF 路径（download=True 时）或 None。
    """
    pn = patent.get("patent_number", "")
    if not pn:
        return None

    tab = _open_detail(result_page, pn)
    if not tab:
        print(f"    [warn] detail 不可达", flush=True)
        return None

    pdf_path = None
    try:
        # ─── 1. 读著录项目 ───
        tab.js("""
        (() => {
            const els = document.querySelectorAll('*');
            for (const el of els) {
                if (el.textContent && el.textContent.trim() === '著录项目'
                    && el.offsetWidth > 0 && el.children.length === 0) {
                    el.click(); return;
                }
            }
        })()
        """)
        time.sleep(2)

        raw = tab.js("""
        (() => {
            const text = document.body.innerText;
            const r = {};
            const ipc = text.match(/IPC分类号[\\s\\n]*([^\\n]+)/);
            if (ipc) r.ipc = ipc[1].trim();
            const cpc = text.match(/CPC分类号[\\s\\n]*([^\\n]+)/);
            if (cpc) r.cpc = cpc[1].trim();
            const app = text.match(/申请（专利权）人[\\s\\n]*([^\\n]+)/);
            if (app) r.assignee = app[1].trim();
            const inv = text.match(/发明人[\\s\\n]*([^\\n]+)/);
            if (inv) r.inventor = inv[1].trim();
            const title = text.match(/发明名称[\\s\\n]*([^\\n]+)/);
            if (title) r.title_biblio = title[1].trim();
            const date = text.match(/申请日[\\s\\n]*(\\d{4}\\.\\d{2}\\.\\d{2})/);
            if (date) r.filing_date = date[1].replace(/\\./g, '-');
            const absIdx = text.indexOf('摘要\\n');
            if (absIdx > 0) {
                let a = text.substring(absIdx + 3, absIdx + 1003).trim();
                const cuts = ['通知公告', '在线提问', '数据收录'];
                let end = a.length;
                for (const c of cuts) { const ci = a.indexOf(c); if (ci > 0 && ci < end) end = ci; }
                r.abstract = a.substring(0, end).trim();
            }
            return JSON.stringify(r);
        })()
        """)

        if raw:
            biblio = json.loads(raw)
            for key in ("ipc", "cpc", "assignee", "inventor", "filing_date", "abstract"):
                if biblio.get(key):
                    patent[key] = biblio[key]
            if biblio.get("title_biblio") and not patent.get("title"):
                patent["title"] = biblio["title_biblio"]

        if not download:
            return None

        # ─── 2. 下载 PDF ───
        print(f"  [dl  ] {pn} ({patent.get('assignee', '')})", flush=True)

        # 用 CDP 鼠标点击切换全文图像 tab
        tab_coords = tab.js("""
        (() => {
            const els = document.querySelectorAll('*');
            for (const el of els) {
                if (el.textContent && el.textContent.trim() === '全文图像'
                    && el.offsetWidth > 0 && el.children.length === 0) {
                    const r = el.getBoundingClientRect();
                    return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
                }
            }
        })()
        """)
        if tab_coords and tab_coords != "":
            try:
                c = json.loads(tab_coords)
                tab.mouse_click(c["x"], c["y"])
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(6)

        # 检查 Foxit iframe
        iframe_check = tab.js("""
        (() => {
            const f = document.querySelector('iframe');
            if (!f) return 'no_iframe';
            if (!f.contentDocument) return 'no_doc';
            const btn = f.contentDocument.getElementById('download');
            return btn ? 'ready' : 'no_btn';
        })()
        """)

        if iframe_check != "ready":
            print(f"  [fail] Foxit: {iframe_check}", flush=True)
            return None

        # 清旧 PDF
        for f in DL_DIR.glob("*.PDF"):
            if (time.time() - f.stat().st_mtime) < 300:
                f.unlink()

        # CDP 鼠标点击 Foxit iframe 内 #download 按钮
        click_ok = tab.click_iframe_button("download")
        print(f"  [click] download button: {'ok' if click_ok else 'fail'}", flush=True)
        if not click_ok:
            print(f"  [fail] 找不到下载按钮", flush=True)
            return None

        # 等 PDF
        for _ in range(20):
            time.sleep(1)
            recent = sorted(
                list(DL_DIR.glob("*.PDF")) + list(DL_DIR.glob("*.pdf")),
                key=lambda p: p.stat().st_mtime, reverse=True
            )
            if recent and (time.time() - recent[0].stat().st_mtime) < 15:
                with open(recent[0], "rb") as f:
                    if f.read(5) == b"%PDF-":
                        pdf_path = recent[0]
                        break

        if not pdf_path:
            # 调试：看 Downloads 最新文件
            all_recent = sorted(DL_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
            print(f"  [debug] recent files:", flush=True)
            for f in all_recent:
                print(f"    {f.name} ({f.stat().st_size//1024}KB, age={time.time()-f.stat().st_mtime:.0f}s)", flush=True)
            print(f"  [fail] PDF 下载超时", flush=True)
            return None

        size_kb = pdf_path.stat().st_size // 1024
        print(f"  [ok  ] PDF ({size_kb}KB)", flush=True)

        # IPC 分类 + 移动
        assignee = patent.get("assignee", "Unknown").strip()
        title = patent.get("title", "No Title")
        safe_title = re.sub(r'[<>:"|?*\\/]', '', title[:60]).strip()
        filename = f"{pn} - [{assignee}] {safe_title}.pdf"

        ipc_dir = classify_by_ipc(patent)
        dest_dir = PATENT_SRC / ipc_dir if ipc_dir else INBOX
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        shutil.move(str(pdf_path), str(dest_path))
        add_to_index(pn, ipc_dir or "inbox")

        label = ipc_dir or "inbox"
        print(f"  [mv  ] → {label}/{filename[:60]}", flush=True)
        return str(dest_path)

    except Exception as e:
        print(f"    [warn] 操作异常: {e}", flush=True)
        return None
    finally:
        try:
            tab.send("Page.close")
        except Exception:
            pass
        tab.close()


# ─── 公开接口 ────────────────────────────────────────────────────────────

def search_patents(page, context, query: str, max_results: int = 10,
                   country: str = "US", pages: int = 1) -> list[dict]:
    """搜索 CNIPA，返回专利列表。"""
    # 确保 page 存活
    try:
        _ = page.url
    except Exception:
        page = context.new_page()

    page.goto(CNIPA_SEARCH, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    _accept_disclaimer(page)
    _select_country(page, country)

    print(f"[search] {query} (country={country})", flush=True)
    _do_search(page, query)

    result_page = _find_result_page(context)
    if not result_page:
        print("[error] 检索结果页未打开", flush=True)
        return []

    total = _get_total_count(result_page)
    print(f"[found] {total} 条数据", flush=True)

    all_patents = []
    for pg in range(pages):
        if pg > 0:
            if not _goto_next_page(result_page):
                print(f"[page ] 第 {pg+1} 页不可用，停止翻页", flush=True)
                break
            time.sleep(2)

        page_patents = _parse_result_list(result_page)
        print(f"[parsed] 第 {pg+1} 页 {len(page_patents)} 篇", flush=True)
        all_patents.extend(page_patents)

    # search-only 模式：只用结果列表的信息（标题/申请人/日期），不逐篇打开 detail
    # 著录详情（IPC/摘要）在下载阶段读取，避免反复开关 detail tab 破坏结果页状态
    for pat in all_patents[:max_results]:
        pat["url"] = f"{CNIPA_URL}/documents/detail?prevPageTit=changgui"

    return all_patents[:max_results]


def download_patents(result_page, patents: list[dict],
                     max_download: int = 10) -> list[str]:
    downloaded = []
    for i, patent in enumerate(patents[:max_download]):
        pn = patent.get("patent_number", "?")
        print(f"\n[{i+1}/{min(len(patents), max_download)}] {patent.get('title', '')[:60]}", flush=True)
        time.sleep(1)
        # 一次打开 detail tab：读著录 + 下载 PDF
        path = _read_and_download(result_page, patent, download=True)
        if path:
            downloaded.append(path)
    return downloaded


def run(query: str, max_papers: int = 10, dry_run: bool = False,
        search_only_flag: bool = False, country: str = "US",
        pages: int = 1, json_out: bool = False) -> list[dict]:
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

    with sync_playwright() as pw:
        ws = get_cdp_ws_url()
        print(f"[cdp  ] 连接 {ws}...", flush=True)
        browser = pw.chromium.connect_over_cdp(ws)
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        # 清理残留 detail tab
        _close_detail_tabs()
        time.sleep(1)

        # 用存活的 tab 导航
        page = None
        for p in list(context.pages):
            try:
                _ = p.url
                page = p
                break
            except Exception:
                pass
        if not page:
            page = context.new_page()

        results = search_patents(page, context, query,
                                 max_results=max_papers * 2, country=country,
                                 pages=pages)

        new_results = [p for p in results if p.get("patent_number", "") not in existing]
        skipped = len(results) - len(new_results)
        print(f"[dedup] 过滤后 {len(new_results)} 篇新（跳过 {skipped} 篇已有）", flush=True)
        new_results = new_results[:max_papers]

        if search_only_flag or dry_run:
            if json_out:
                print("\n---CANDIDATES---")
                print(json.dumps(new_results, ensure_ascii=False, indent=2))
            else:
                for i, p in enumerate(new_results, 1):
                    marker = " [已有]" if p.get("patent_number", "") in existing else ""
                    print(f"  {i}. [{p.get('patent_number', '?')}] {p.get('title', '')[:80]}{marker}")
                    print(f"     {p.get('assignee', '')} | IPC: {p.get('ipc', '')} | {p.get('filing_date', '')}")
                    if p.get("abstract"):
                        print(f"     {p['abstract'][:120]}...")
            if dry_run:
                print(f"\n[dry  ] 共 {len(new_results)} 篇（dry-run，未下载）")
            return new_results

        result_page = None
        for p in context.pages:
            if "retrieveList" in p.url:
                result_page = p
                break

        if result_page:
            paths = download_patents(result_page, new_results)
            print(f"\n[done ] 下载完成：{len(paths)}/{len(new_results)} 篇", flush=True)
            if paths:
                print("[next ] 运行 patent_convert.py 转换新专利", flush=True)
        else:
            print("[error] 未找到结果页，无法下载", flush=True)

    return new_results


def run_patent_numbers(patent_numbers: list[str], dry_run: bool = False) -> list[str]:
    """按指定专利号批量下载。每个号单独搜索，取第一条结果下载。

    等价于逐个执行：
        patent_search_cnipa.py "<号>" --max 1

    Args:
        patent_numbers: 专利号列表，如 ["US2024264619A1", "US2025216882A1"]
        dry_run: True 时只打印不下载

    Returns:
        已成功下载的 PDF 路径列表
    """
    if not ensure_cdp():
        print("[error] 无法启动研究 Chrome")
        sys.exit(1)

    print("[dedup] 读取专利索引...", flush=True)
    existing = get_patent_numbers()
    print(f"[dedup] 本地已有 {len(existing)} 篇专利", flush=True)

    # 过滤已有专利
    to_download = [n for n in patent_numbers if n not in existing]
    skipped = [n for n in patent_numbers if n in existing]
    if skipped:
        print(f"[dedup] 跳过 {len(skipped)} 篇已有：{', '.join(skipped)}", flush=True)
    if not to_download:
        print("[done ] 所有指定专利已在本地，无需下载", flush=True)
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[error] playwright 未安装")
        sys.exit(1)

    downloaded_paths = []
    print(f"\n[plan ] 计划下载 {len(to_download)} 篇: {', '.join(to_download)}", flush=True)

    with sync_playwright() as pw:
        ws = get_cdp_ws_url()
        print(f"[cdp  ] 连接 {ws}...", flush=True)
        browser = pw.chromium.connect_over_cdp(ws)
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        _close_detail_tabs()
        time.sleep(1)

        page = None
        for p in list(context.pages):
            try:
                _ = p.url
                page = p
                break
            except Exception:
                pass
        if not page:
            page = context.new_page()

        for i, pn in enumerate(to_download, 1):
            print(f"\n[{i}/{len(to_download)}] {pn}", flush=True)
            if dry_run:
                print(f"  [dry ] 跳过（dry-run）")
                continue

            # 关闭上轮遗留的 retrieveList tab，确保新搜索结果可被精确定位
            for p in list(context.pages):
                try:
                    if "retrieveList" in p.url:
                        p.close()
                except Exception:
                    pass
            time.sleep(0.5)

            # 每个专利号作为精确查询词
            results = search_patents(page, context, pn,
                                     max_results=1, country="US", pages=1)
            if not results:
                print(f"  [warn] 搜索无结果，跳过 {pn}", flush=True)
                continue

            patent = results[0]
            # 校验专利号匹配（CNIPA 精确搜索一般命中准确）
            found_pn = patent.get("patent_number", "")
            if found_pn and found_pn.upper() != pn.upper():
                print(f"  [warn] 专利号不匹配（期望 {pn}，得到 {found_pn}），跳过", flush=True)
                continue

            # 找 result_page（刚刚新开的，旧 tab 已在循环头关闭）
            result_page = None
            for p in context.pages:
                try:
                    if "retrieveList" in p.url:
                        result_page = p
                        break
                except Exception:
                    pass

            if not result_page:
                print(f"  [warn] 未找到结果页，跳过 {pn}", flush=True)
                continue

            paths = download_patents(result_page, [patent])
            downloaded_paths.extend(paths)
            time.sleep(1)  # 礼貌间隔

    print(f"\n[done ] 下载完成：{len(downloaded_paths)}/{len(to_download)} 篇", flush=True)
    if downloaded_paths:
        print("[next ] 运行 patent_convert.py 转换新专利", flush=True)
    return downloaded_paths


def main():
    parser = argparse.ArgumentParser(
        description="CNIPA 专利检索下载（Chrome CDP，国内直连）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
定位：Google Patents 不可用时的首选 fallback。

示例:
  python patent_search_cnipa.py "buck converter"
  python patent_search_cnipa.py "SAR ADC switching" --max 5
  python patent_search_cnipa.py "dToF SPAD" --search-only
  python patent_search_cnipa.py "buck converter" --dry-run
  python patent_search_cnipa.py "降压转换器" --country CN
  python patent_search_cnipa.py --patent-numbers US2024264619A1 US2025216882A1 US2025321603A1
        """
    )
    parser.add_argument("query", nargs="*", help="搜索关键词（与 --patent-numbers 二选一）")
    parser.add_argument("--patent-numbers", nargs="+", metavar="PN",
                        help="直接指定专利号批量下载，无需关键词搜索（两段式评分后用此精确下载）")
    parser.add_argument("--max", type=int, default=10, help="最大结果数 (default: 10)")
    parser.add_argument("--search-only", action="store_true", help="仅搜索，不下载")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="以 JSON 格式输出候选列表（与 --search-only 配合，供 pipeline 解析）")
    parser.add_argument("--dry-run", action="store_true", help="列出但不下载")
    parser.add_argument("--country", type=str, default="US",
                        help="专利国家 (default: US)")
    parser.add_argument("--pages", type=int, default=1,
                        help="翻页数（CNIPA 按时间排序，非相关性；多页防遗漏）(default: 1)")
    args = parser.parse_args()

    if args.patent_numbers:
        # 专利号直接下载模式
        run_patent_numbers(args.patent_numbers, dry_run=args.dry_run)
    elif args.query:
        query = " ".join(args.query)
        run(query, max_papers=args.max, dry_run=args.dry_run,
            search_only_flag=args.search_only, country=args.country,
            pages=args.pages, json_out=args.json_out)
    else:
        parser.error("请提供搜索关键词，或使用 --patent-numbers 指定专利号")


if __name__ == "__main__":
    main()
