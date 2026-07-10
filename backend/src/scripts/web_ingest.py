#!/usr/bin/env python3
"""
Web 资源自动入库：PDF→pymupdf4llm→MD / HTML→MD，统一存入 raw/web/。

用法:
  python web_ingest.py <url> --topic <topic>                 # 单个 URL
  python web_ingest.py <url1> <url2> --topic <topic>         # 多个 URL
  python web_ingest.py <url> --topic <topic> --dry-run       # 仅预览
  python web_ingest.py <url> --topic <topic> --workers 2     # 并行（多 URL 时）

流程:
  - 检测 URL Content-Type
  - PDF: curl 下载 → pymupdf4llm 转 MD（含图片）→ 写入 raw/web/<topic>/ → 写 frontmatter
  - HTML: 直接请求 → html→markdown → 写入 raw/web/<topic>/ → 写 frontmatter
"""

import argparse
import mimetypes
import os
import pathlib
import re
import shutil
import time
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import urlparse

VAULT = pathlib.Path(os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib")))
RAW_WEB = VAULT / "raw" / "web"
DOWNLOADS = pathlib.Path(os.environ.get("WEB_DOWNLOAD_DIR", str(pathlib.Path.home() / "Downloads" / "web_articles")))

# HTML→MD 可用库（按优先级）
try:
    import markdownify
    HAS_MARKDOWNIFY = True
except ImportError:
    HAS_MARKDOWNIFY = False

try:
    from html.parser import HTMLParser
except ImportError:
    pass


def detect_type(url: str, timeout: int = 15) -> str:
    """通过 HEAD 请求检测 Content-Type，返回 'pdf' / 'html' / 'unknown'。"""
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "pdf" in ct.lower():
                return "pdf"
            if "html" in ct.lower():
                return "html"
            # fallback: 检查 URL 后缀
            if url.lower().endswith(".pdf"):
                return "pdf"
            return "html"
    except urllib.error.HTTPError as e:
        # HEAD 被拒，尝试 GET 的一小部分
        if url.lower().endswith(".pdf"):
            return "pdf"
        return "html"
    except Exception as e:
        print(f"  [warn] 无法检测类型: {e}，按 URL 后缀判断")
        return "pdf" if url.lower().endswith(".pdf") else "html"


def slugify(text: str, max_len: int = 80) -> str:
    """生成文件名友好的 slug。"""
    text = re.sub(r"[^\w\s\-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]


def download_pdf(url: str, dest_dir: pathlib.Path, slug: str) -> pathlib.Path | None:
    """curl 下载 PDF 到目标目录。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug}.pdf"

    # 检查大小
    req = urllib.request.Request(url)
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [err ] 下载失败: {e}")
        return None

    # 校验 PDF 文件头
    if not data.startswith(b"%PDF-"):
        print(f"  [warn] 非有效 PDF（文件头: {data[:20]}），可能为 HTML 伪装")
        return None

    dest.write_bytes(data)
    size_kb = len(data) / 1024
    print(f"  [dl  ] {slug}.pdf ({size_kb:.0f} KB)")
    return dest


def convert_pdf(pdf_path: pathlib.Path, out_base: pathlib.Path, slug: str,
                url: str = "", device: str = "cpu") -> pathlib.Path | None:
    """Convert a single PDF → MD. Uses MinerU cloud API when MINERU_API_TOKEN is set,
    falls back to pymupdf4llm otherwise. Supports slug collision deduplication."""
    t0 = time.time()

    final_dir = out_base / slug
    final_slug = slug

    # slug 碰撞去重：同 slug 但不同来源 URL → 加 hash 后缀
    if final_dir.exists() and url:
        existing_md = final_dir / f"{slug}.md"
        if existing_md.exists():
            existing_content = existing_md.read_text(encoding="utf-8", errors="replace")
            source_match = re.search(r'^source:\s*"?([^"\n]+)"?', existing_content, re.MULTILINE)
            existing_url = source_match.group(1).strip() if source_match else ""
            if existing_url and existing_url != url:
                import hashlib
                url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
                final_slug = f"{slug}_{url_hash}"
                final_dir = out_base / final_slug
                print(f"  [dedup] slug 碰撞，改为 {final_slug}（不同 URL）")

    # Try cloud API first
    cloud_token = os.environ.get("MINERU_API_TOKEN", "")
    if cloud_token:
        try:
            import sys as _sys
            _sys.path.insert(0, str(pathlib.Path(__file__).parent))
            from mineru_cloud import convert_pdf_cloud
            import tempfile as _tmp
            tmp_out = pathlib.Path(_tmp.mkdtemp(prefix="mineru_web_"))
            name, status, elapsed, error = convert_pdf_cloud(
                pdf_path, tmp_out, token=cloud_token,
            )
            if status == "ok":
                # cloud writes to tmp_out/<safe_stem>/; rename to final_dir
                safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", pdf_path.stem)
                src_dir = tmp_out / safe_stem
                if not src_dir.exists():
                    subdirs = [d for d in tmp_out.iterdir() if d.is_dir()]
                    src_dir = subdirs[0] if subdirs else tmp_out

                if final_dir.exists():
                    import shutil as _sh
                    _sh.rmtree(final_dir)
                import shutil as _sh
                _sh.move(str(src_dir), str(final_dir))
                _sh.rmtree(tmp_out, ignore_errors=True)

                # Find and rename the md to final_slug.md
                mds = list(final_dir.glob("*.md"))
                if mds:
                    dest_md = final_dir / f"{final_slug}.md"
                    if mds[0] != dest_md:
                        mds[0].rename(dest_md)
                    # MinerU emits relative ![](images/x.jpg) links — keep them as-is
                    # so they render in the web viewer / Obsidian / any markdown tool.
                    print(f"  [cloud] {dest_md.name} ({elapsed:.0f}s)")
                    return dest_md
            else:
                import shutil as _sh
                _sh.rmtree(tmp_out, ignore_errors=True)
                print(f"  [warn] cloud convert failed: {error}，fallback to pymupdf4llm")
        except Exception as e:
            print(f"  [warn] cloud convert error: {e}，fallback to pymupdf4llm")

    # Fallback: pymupdf4llm
    try:
        import pymupdf4llm

        final_dir.mkdir(parents=True, exist_ok=True)
        img_dir = final_dir / "images"
        img_dir.mkdir(exist_ok=True)

        md_text = pymupdf4llm.to_markdown(
            str(pdf_path),
            write_images=True,
            image_path=str(img_dir),
            image_format="png",
        )

        # pymupdf4llm bakes the absolute image_path into every ![](...) link;
        # rewrite that absolute prefix to a relative "images/" path.
        abs_prefix = str(img_dir).replace("\\", "/").rstrip("/") + "/"
        md_text = md_text.replace(abs_prefix, "images/")

        dest_md = final_dir / f"{final_slug}.md"
        dest_md.write_text(md_text, encoding="utf-8")

        elapsed = time.time() - t0
        print(f"  [conv ] {dest_md.name} ({elapsed:.0f}s)")
        return dest_md

    except Exception as e:
        print(f"  [fail] convert_pdf 异常: {e}")
        return None


def html_to_markdown(html: str) -> str:
    """HTML → 纯文本 Markdown（优先 markdownify，回退简单提取）。"""
    if HAS_MARKDOWNIFY:
        return markdownify.markdownify(html, heading_style="ATX")

    # 简单回退：去标签
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", "", clean)
    clean = re.sub(r"\n\s*\n\s*\n+", "\n\n", clean)
    return clean.strip()


def fetch_html(url: str) -> str | None:
    """GET HTML 页面内容。"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        # 尝试 curl 回退
        print(f"  [warn] urllib 失败: {e}，尝试 curl")
        try:
            result = subprocess.run(
                ["curl", "-sL", "-A",
                 "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                 url],
                capture_output=True, timeout=30)
            if result.returncode == 0 and result.stdout:
                return result.stdout.decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"  [err ] 无法获取 HTML: {e}")
        return None


def write_frontmatter(md_path: pathlib.Path, url: str, title: str = "",
                      source_date: str = "") -> None:
    """向 MD 写入 frontmatter。"""
    content = md_path.read_text(encoding="utf-8", errors="replace")
    if content.lstrip().startswith("---"):
        return  # 已有 frontmatter

    if not source_date:
        source_date = datetime.now().strftime("%Y-%m-%d")
    if not title:
        title = md_path.stem.replace("_", " ")

    fm = f"""---
title: "{title}"
source: "{url}"
date_saved: {source_date}
tags:
  - web-clipping
type: web-clipping
---

{content.lstrip()}
"""
    md_path.write_text(fm, encoding="utf-8")


def ingest_one(url: str, topic: str, dry_run: bool = False,
               device: str = "mps") -> tuple[str, str, str]:
    """处理单个 URL。返回 (url, status, detail)。"""
    print(f"\n{'[dry ]' if dry_run else '[ing ]'} {url[:100]}")

    dtype = detect_type(url)
    print(f"  [type] {dtype}")

    dest_dir = RAW_WEB / topic
    parsed = urlparse(url)
    stem = pathlib.Path(parsed.path).stem or slugify(parsed.netloc + parsed.path)
    slug = slugify(stem)

    if dtype == "pdf":
        if dry_run:
            return url, "dry_pdf", slug
        dl_dir = DOWNLOADS / topic
        pdf = download_pdf(url, dl_dir, slug)
        if not pdf:
            return url, "fail", "下载失败或非有效 PDF"
        md_path = convert_pdf(pdf, dest_dir, slug, url=url, device=device)
        if not md_path:
            return url, "fail", "PDF 转换失败"
        write_frontmatter(md_path, url,
                          title=slug.replace("_", " "),
                          source_date=datetime.now().strftime("%Y-%m-%d"))
        return url, "ok_pdf", str(md_path.relative_to(VAULT))

    else:  # html
        if dry_run:
            return url, "dry_html", slug
        html = fetch_html(url)
        if not html:
            return url, "fail", "无法获取页面"
        markdown = html_to_markdown(html)
        if not markdown or len(markdown) < 50:
            return url, "fail", "提取内容过短"

        dest_dir.mkdir(parents=True, exist_ok=True)
        md_path = dest_dir / f"{slug}.md"

        # 检查是否已有同名文件且来自同一 URL（source 字段）
        # 若是，覆盖更新；否则加时间戳避免冲突
        if md_path.exists():
            existing_content = md_path.read_text(encoding="utf-8", errors="replace")
            source_match = re.search(r'^source:\s*"?([^"\n]+)"?', existing_content, re.MULTILINE)
            existing_url = source_match.group(1).strip() if source_match else ""

            if existing_url != url:
                # 不同 URL，加时间戳避免冲突
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                md_path = dest_dir / f"{slug}_{ts}.md"

        md_path.write_text(markdown, encoding="utf-8")
        write_frontmatter(md_path, url,
                          title=slug.replace("_", " "),
                          source_date=datetime.now().strftime("%Y-%m-%d"))
        print(f"  [saved] {md_path.name} ({len(markdown)} chars)")
        return url, "ok_html", str(md_path.relative_to(VAULT))


def main():
    parser = argparse.ArgumentParser(
        description="Web 资源自动入库：PDF→MD / HTML→MD → raw/web/")
    parser.add_argument("urls", nargs="+", help="URL(s) 待入库")
    parser.add_argument("--topic", required=True,
                        help="raw/web/ 下的目标子目录（如 MEMS_Stiction）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不下载")
    parser.add_argument("--workers", type=int, default=1,
                        help="并行数（默认 1，PDF 多文件时可设 2-4）")
    parser.add_argument("--device", default="cpu",
                        help="(unused, kept for CLI compatibility)")
    args = parser.parse_args()

    print(f"[web_ingest] {len(args.urls)} URL(s) → raw/web/{args.topic}/")

    if args.workers > 1 and len(args.urls) > 1:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(ingest_one, u, args.topic, args.dry_run, args.device): u
                    for u in args.urls}
            for f in concurrent.futures.as_completed(futs):
                url, status, detail = f.result()
                print(f"  [{status}] {detail[:80]}")
    else:
        ok = fail = 0
        for url in args.urls:
            _, status, detail = ingest_one(url, args.topic, args.dry_run, args.device)
            if status.startswith("ok"):
                ok += 1
            elif status.startswith("fail"):
                fail += 1

        print(f"\n[web_ingest] done: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
