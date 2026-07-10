#!/usr/bin/env python3
"""CDP Chrome 自动管理模块。

被 ieee_search.py / patent_search.py / scholar_search.py 导入。
自动检测 CDP 端口，未启动时自动运行 launch_research_chrome.sh。

用法:
    from _cdp_helper import ensure_cdp, get_cdp_ws_url
    if not ensure_cdp():
        sys.exit(1)
    # 之后用 playwright 连接 ws URL（Chrome 148+ 需要 ws://，不能用 http://）
    browser = playwright.chromium.connect_over_cdp(get_cdp_ws_url())
"""

import json as _json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
CDP_URL = f"http://localhost:{CDP_PORT}"
LAUNCH_SCRIPT = pathlib.Path(__file__).parent / "launch_research_chrome.sh"

# 研究 Chrome 的独立 profile（持久化 IEEE/CNIPA 登录态），可用环境变量覆盖。
CHROME_PROFILE = pathlib.Path(
    os.environ.get("RESEARCH_CHROME_PROFILE", str(pathlib.Path.home() / "research-chrome-profile"))
)


def check_cdp_port() -> bool:
    """检查 CDP 端口是否开放。"""
    try:
        s = socket.create_connection(("localhost", CDP_PORT), timeout=2)
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def get_cdp_ws_url() -> str:
    """Return the CDP WebSocket URL suitable for playwright connect_over_cdp().

    Chrome 148+ rejects playwright's HTTP fetch of the CDP endpoint (HTTP 400)
    but the ws:// URL from /json/version works fine.  We resolve it via plain
    urllib so no Origin header is sent.
    """
    try:
        data = _json.loads(
            urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=5).read()
        )
        return data["webSocketDebuggerUrl"]
    except Exception as e:
        raise RuntimeError(f"[cdp] 无法获取 CDP WebSocket URL: {e}") from e


def find_chrome() -> str | None:
    """跨平台定位 Chrome（或 Edge）可执行文件。

    优先级：环境变量 CHROME_BIN → 各平台常见安装路径 → PATH 中的 chromium。
    """
    env_bin = os.environ.get("CHROME_BIN")
    if env_bin and pathlib.Path(env_bin).exists():
        return env_bin

    candidates: list[str] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
            # CDP 同样适用于 Edge（Chromium 内核），作为兜底
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:  # linux
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                return found

    for c in candidates:
        if c and pathlib.Path(c).exists():
            return c
    return None


def _launch_chrome() -> bool:
    """以独立 profile + CDP 端口启动 Chrome。返回是否成功发出启动命令。"""
    chrome = find_chrome()
    if chrome:
        CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        cmd = [
            chrome,
            f"--remote-debugging-port={CDP_PORT}",
            # Chrome 111+ rejects CDP websocket connections unless the origin is
            # explicitly allowed; Playwright's connect_over_cdp needs this.
            "--remote-allow-origins=*",
            f"--user-data-dir={CHROME_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            # Chrome 148 broke CDP protocol handshake; --enable-automation restores
            # the legacy behavior needed by Playwright 1.60.
            "--enable-automation",
        ]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            print(f"[error] 启动 Chrome 失败: {e}", flush=True)
            return False

    # 兜底：macOS/Linux 上若有历史 bash 启动脚本则沿用
    if LAUNCH_SCRIPT.exists() and sys.platform != "win32":
        try:
            subprocess.Popen(
                ["bash", str(LAUNCH_SCRIPT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            print(f"[error] 启动失败: {e}", flush=True)
            return False

    print(
        f"[error] 未找到 Chrome。请手动启动并带上 --remote-debugging-port={CDP_PORT}，"
        "或设置环境变量 CHROME_BIN 指向 chrome.exe。",
        flush=True,
    )
    return False


def ensure_cdp(timeout: int = 30) -> bool:
    """确保 CDP Chrome 已启动。未启动时跨平台自动拉起并等待端口就绪。

    Returns:
        True 如果 CDP 端口已就绪，False 如果超时或无法启动。
    """
    if check_cdp_port():
        return True

    print("[auto ] CDP 端口未检测到，自动启动研究 Chrome...", flush=True)
    if not _launch_chrome():
        return False

    # 等待端口就绪
    waited = 0
    while waited < timeout:
        if check_cdp_port():
            print(f"[auto ] Chrome CDP 已就绪 (waited {waited}s)", flush=True)
            # 额外给 Chrome 一点时间完成初始化
            time.sleep(1)
            return True
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            print(f"  ... 等待 CDP 端口 ({waited}s)", flush=True)

    print(f"[error] CDP 启动超时 ({timeout}s)", flush=True)
    return False


def check_ieee_auth(page) -> bool:
    """检查 IEEE Xplore 机构认证状态。

    通过检测页面是否显示登录提示或 Institution 标志判断。
    """
    try:
        auth_status = page.evaluate("""() => {
            const signIn = document.querySelector('a[href*="login"]');
            const signOut = document.querySelector('a[href*="logout"], a[href*="signout"], a:contains("Sign Out")');
            if (signOut) return true;
            const inst = document.querySelector('.institution, .inst-name, [data-testid="institution"]');
            if (inst && inst.textContent.trim().length > 0) return true;
            // 检查是否显示 Sign In（未登录状态）
            const body = document.body.textContent;
            if (body.includes('Sign In') && !body.includes('Sign Out')) return false;
            return !signIn;  // 没有 Sign In 按钮 = 已登录
        }""")
        return bool(auth_status)
    except Exception:
        return True  # 无法判断时放行


def auth_alert(msg: str) -> None:
    """打印认证失效警告。"""
    print(f"\n{'='*60}", flush=True)
    print(f"[AUTH] {msg}", flush=True)
    print(f"[AUTH] 请在研究 Chrome 中重新登录 IEEE Xplore。", flush=True)
    print(f"[AUTH] 登录后输入 r 重试 / q 退出。", flush=True)
    print(f"{'='*60}\n", flush=True)
