#!/usr/bin/env python3
"""自动登录 CNIPA / IEEE 到研究 Chrome（CDP 连接）。

从 .env 读取账密，登录后 session cookie 保存在 Chrome profile，之后脚本无需重复登录。

用法:
  python login_research_sites.py          # 登录全部（CNIPA + IEEE）
  python login_research_sites.py --cnipa  # 只登录 CNIPA
  python login_research_sites.py --ieee   # 只登录 IEEE
"""

import argparse
import os
import pathlib
import sys
import time

# 加载 .env
_env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _cdp_helper import ensure_cdp, get_cdp_ws_url


# ─── CNIPA ───────────────────────────────────────────────────────────────────

CNIPA_LOGIN_URL = "https://tysf.cponline.cnipa.gov.cn/am/#/user/login"
CNIPA_HOME = "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch"


def login_cnipa(page, username: str, password: str) -> bool:
    print("[cnipa] 导航登录页...", flush=True)
    page.goto(CNIPA_LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)

    try:
        # 用户名输入框
        user_inp = page.locator("input[placeholder*='用户名'], input[name='username'], input[type='text']").first
        user_inp.wait_for(state="visible", timeout=8000)
        user_inp.fill(username)
        time.sleep(0.3)

        # 密码输入框
        pwd_inp = page.locator("input[type='password']").first
        pwd_inp.fill(password)
        time.sleep(0.3)

        # 提交
        submit = page.locator("button[type='submit'], .login-btn, button:has-text('登录')").first
        submit.click(timeout=5000)
        print("[cnipa] 已提交登录...", flush=True)
    except Exception as e:
        print(f"[cnipa] 填表失败: {e}", flush=True)
        return False

    # 等待跳转到主站
    for _ in range(30):
        time.sleep(1)
        if "pss-system.cponline.cnipa.gov.cn" in page.url:
            print(f"[cnipa] ✅ 登录成功，当前页: {page.url}", flush=True)
            return True
        if "error" in page.url.lower() or "fail" in page.url.lower():
            print(f"[cnipa] ❌ 登录失败，URL: {page.url}", flush=True)
            return False

    # 检查是否仍在登录页（账密错误）
    if "login" in page.url.lower():
        try:
            err = page.locator(".error-msg, .el-form-item__error, [class*=error]").first
            err_text = err.inner_text(timeout=2000)
            print(f"[cnipa] ❌ 登录失败: {err_text}", flush=True)
        except Exception:
            print(f"[cnipa] ❌ 登录超时，仍在: {page.url}", flush=True)
        return False

    print(f"[cnipa] ⚠️ 未知状态: {page.url}", flush=True)
    return False


# ─── IEEE ────────────────────────────────────────────────────────────────────

IEEE_WEBVPN_ENTRY = os.environ.get("IEEE_WEBVPN_ENTRY", "")
IEEE_HOME = "https://ieeexplore.ieee.org"


def check_ieee_auth(page) -> bool:
    """检查 IEEE 机构认证是否有效（能下 PDF 视为已认证）。"""
    try:
        body = page.evaluate("() => document.body.innerText")
        if "Sign Out" in body or "Log Out" in body:
            return True
        # 检查右上角机构标识
        inst = page.evaluate("""() => {
            const el = document.querySelector('.institution-badge, [data-analytics-tag*="institution"]');
            return el ? el.innerText : '';
        }""")
        if inst and len(inst.strip()) > 0:
            return True
        return False
    except Exception:
        return False


def activate_ieee_webvpn(page) -> bool:
    """访问 WebVPN 入口页，找到并点击「访问」链接，跳转到 ieeexplore.ieee.org。"""
    if not IEEE_WEBVPN_ENTRY:
        print("[ieee ] 未配置 IEEE_WEBVPN_ENTRY，跳过 WebVPN 激活", flush=True)
        return False

    print(f"[ieee ] 访问 WebVPN 入口: {IEEE_WEBVPN_ENTRY[:80]}", flush=True)
    try:
        page.goto(IEEE_WEBVPN_ENTRY, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        cur = page.url
        print(f"[ieee ] 入口页当前 URL: {cur[:80]}", flush=True)

        if "ieeexplore.ieee.org" in cur:
            print("[ieee ] ✅ 已直接跳转到 IEEE Xplore", flush=True)
            return True

        # 找直接指向 ieeexplore.ieee.org 的链接，或平台跳转链接
        ieee_href = page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            const direct = links.find(a => a.href.includes('ieeexplore.ieee.org'));
            if (direct) return direct.href;
            const out = links.find(a =>
                /goOut|outLink|visit|访问|进入/i.test(a.href + a.textContent)
            );
            return out ? out.href : null;
        }""")

        if ieee_href:
            print(f"[ieee ] 找到访问链接，导航: {ieee_href[:80]}", flush=True)
            page.goto(ieee_href, wait_until="domcontentloaded", timeout=25000)
            time.sleep(4)
            print(f"[ieee ] 跳转后 URL: {page.url[:80]}", flush=True)
            if "ieeexplore.ieee.org" in page.url:
                print("[ieee ] ✅ WebVPN session 已激活，已跳转到 IEEE Xplore", flush=True)
                return True
            print(f"[ieee ] ⚠️ 跳转后未到 IEEE，当前在: {page.url[:80]}", flush=True)
            return False

        # 未找到链接 — 判断是否在登录页
        body = page.evaluate("() => document.body.innerText.substring(0, 300)")
        if any(kw in body for kw in ["统一认证", "用户名", "密码", "login", "Login", "账号"]):
            print("[ieee ] ⚠️  需要校园账号登录 WebVPN 认证", flush=True)
            print("[ieee ]    请在研究 Chrome 窗口中手动完成登录，然后重新运行此脚本", flush=True)
            return False

        print(f"[ieee ] ⚠️  页面上未找到 IEEE 访问链接，当前在: {cur[:80]}", flush=True)
        return False

    except Exception as e:
        print(f"[ieee ] WebVPN 激活失败: {e}", flush=True)
        return False


def login_ieee(page) -> bool:
    """尝试通过 WebVPN 或直连激活 IEEE 机构认证。"""
    print("[ieee ] 检查 IEEE Xplore 认证状态...", flush=True)

    # 先访问 IEEE 主页
    page.goto(IEEE_HOME, wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    if check_ieee_auth(page):
        print("[ieee ] ✅ 已通过机构认证", flush=True)
        return True

    # 尝试 WebVPN 激活
    if IEEE_WEBVPN_ENTRY:
        ok = activate_ieee_webvpn(page)
        if ok:
            # 回到 IEEE 主页验证
            page.goto(IEEE_HOME, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            if check_ieee_auth(page):
                print("[ieee ] ✅ WebVPN 激活后认证成功", flush=True)
                return True
        return ok

    print("[ieee ] ❌ 未配置 WebVPN 且未检测到认证", flush=True)
    print("[ieee ]    请连接机构 VPN 或在 .env 中设置 IEEE_WEBVPN_ENTRY", flush=True)
    return False


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="自动登录研究 Chrome 到 CNIPA/IEEE")
    parser.add_argument("--cnipa", action="store_true", help="只登录 CNIPA")
    parser.add_argument("--ieee", action="store_true", help="只登录 IEEE")
    args = parser.parse_args()

    do_cnipa = args.cnipa or not args.ieee  # 默认两个都做
    do_ieee = args.ieee or not args.cnipa

    if not ensure_cdp():
        print("[error] 无法连接研究 Chrome，请确认 CDP 端口 9222 已开放")
        sys.exit(1)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(get_cdp_ws_url())
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        if do_cnipa:
            username = os.environ.get("CNIPA_USERNAME", "").strip()
            password = os.environ.get("CNIPA_PASSWORD", "").strip()
            if not username or not password:
                print("[cnipa] 跳过：.env 中 CNIPA_USERNAME / CNIPA_PASSWORD 未填写")
            else:
                page = context.new_page()
                ok = login_cnipa(page, username, password)
                if ok:
                    # 跳转到搜索页确认 session 有效
                    page.goto(CNIPA_HOME, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(2)
                    title = page.title()
                    print(f"[cnipa] 搜索页标题: {title}")
                page.close()

        if do_ieee:
            page = context.new_page()
            login_ieee(page)
            page.close()


if __name__ == "__main__":
    main()
