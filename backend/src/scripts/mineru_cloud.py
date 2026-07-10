#!/usr/bin/env python3
"""MinerU Cloud API helper — converts a single PDF to Markdown via mineru.net.

Flow:
  1. POST /api/v4/file-urls/batch  → batch_id + presigned OSS upload URL
  2. PUT PDF bytes → presigned URL (using http.client to avoid urllib adding Content-Type)
  3. Poll GET /api/v4/extract-results/batch/{batch_id} until state=done
  4. Download result zip via CDN, extract full.md + images/

Set MINERU_API_TOKEN env var (JWT) to enable; falls back to local CLI when unset.
"""

import http.client
import io
import json
import os
import pathlib
import re
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Optional

MINERU_BASE_URL = "https://mineru.net/api/v4"
POLL_INTERVAL = 5      # seconds between status polls
MAX_WAIT = 600         # 10 minutes total timeout


def _post_json(url: str, token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _put_oss(url: str, pdf_bytes: bytes) -> None:
    """PUT bytes to an Aliyun OSS presigned URL.

    OSS presigned URLs are signed without a Content-Type header, so any
    extra header changes the signature and causes 403. Use http.client
    directly to send no headers beyond Host and Content-Length.
    """
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=120)
    path_with_qs = parsed.path + ("?" + parsed.query if parsed.query else "")
    conn.request("PUT", path_with_qs, body=pdf_bytes, headers={})
    resp = conn.getresponse()
    resp.read()
    if resp.status not in (200, 204):
        raise RuntimeError(f"OSS upload failed: HTTP {resp.status} {resp.reason}")


def _download_bytes(url: str) -> bytes:
    """Download via http.client (more reliable than urllib for CDN URLs)."""
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=120)
    path_with_qs = parsed.path + ("?" + parsed.query if parsed.query else "")
    conn.request("GET", path_with_qs, headers={"User-Agent": "mineru-python-client"})
    resp = conn.getresponse()
    if resp.status != 200:
        resp.read()
        raise RuntimeError(f"Download failed: HTTP {resp.status} {resp.reason}")
    return resp.read()


def convert_pdf_cloud(
    pdf_path: pathlib.Path,
    out_dir: pathlib.Path,
    token: Optional[str] = None,
    enable_formula: bool = True,
    enable_table: bool = True,
    on_poll: Optional[callable] = None,
) -> tuple[str, str, float, str]:
    """Convert PDF via MinerU cloud API.

    Returns (pdf_name, status, elapsed_seconds, error_message).
    status: "ok" | "fail"

    On success, writes <out_dir>/<safe_stem>/<safe_stem>.md plus images/.
    """
    token = token or os.environ.get("MINERU_API_TOKEN", "")
    if not token:
        return pdf_path.name, "fail", 0.0, "MINERU_API_TOKEN not set"

    t0 = time.time()
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", pdf_path.stem)

    try:
        # Step 1: request presigned upload URL
        r1 = _post_json(
            f"{MINERU_BASE_URL}/file-urls/batch",
            token,
            {
                "enable_formula": enable_formula,
                "enable_table": enable_table,
                "files": [{"url": "", "name": f"{safe_stem}.pdf", "is_ocr": False}],
            },
        )
        if r1.get("code", -1) != 0:
            return pdf_path.name, "fail", time.time() - t0, f"file-urls/batch error: {r1}"

        batch_id: str = r1["data"]["batch_id"]
        upload_url: str = r1["data"]["file_urls"][0]

        # Step 2: upload PDF
        _put_oss(upload_url, pdf_path.read_bytes())

        # Step 3: poll for completion
        deadline = time.time() + MAX_WAIT
        max_polls = MAX_WAIT // POLL_INTERVAL
        poll_count = 0
        result_url = None
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            poll_count += 1
            if on_poll:
                on_poll(int(poll_count), int(max_polls))
            r2 = _get_json(f"{MINERU_BASE_URL}/extract-results/batch/{batch_id}", token)
            if r2.get("code", -1) != 0:
                return pdf_path.name, "fail", time.time() - t0, f"poll error: {r2}"

            files = r2["data"].get("extract_result", [])
            if not files:
                continue
            state = files[0].get("state", "")
            if state == "done":
                result_url = files[0].get("full_zip_url") or files[0].get("zip_url")
                break
            if state in ("failed", "error"):
                err = files[0].get("err_msg", "unknown")
                return pdf_path.name, "fail", time.time() - t0, f"cloud extraction failed: {err}"

        if not result_url:
            return pdf_path.name, "fail", time.time() - t0, "timeout waiting for cloud result"

        # Step 4: download and extract the result zip
        # Zip structure: flat — full.md + images/<hash>.jpg + *_model.json etc.
        zip_bytes = _download_bytes(result_url)

        final_dir = out_dir / safe_stem
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.mkdir(parents=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for entry in zf.namelist():
                # Keep only full.md and images/*; discard model/json intermediates
                name = entry
                if name == "full.md" or name.startswith("images/"):
                    dest = final_dir / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(entry))

        # Rename full.md → <safe_stem>.md
        src_md = final_dir / "full.md"
        if not src_md.exists():
            return pdf_path.name, "fail", time.time() - t0, "full.md not found in zip"

        dst_md = final_dir / f"{safe_stem}.md"
        src_md.rename(dst_md)

        return pdf_path.name, "ok", time.time() - t0, ""

    except Exception as e:
        return pdf_path.name, "fail", time.time() - t0, str(e)
