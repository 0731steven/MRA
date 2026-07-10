import os
import sys
import json
import asyncio
from pathlib import Path

# Per-script subprocess timeout (seconds).  Browser-driven scripts need more
# time because they wait on Chrome/IEEE/CNIPA network responses.
_TIMEOUT_DEFAULT = 120
_TIMEOUT_BROWSER = 300   # ieee_search, patent_search, web_ingest

_BROWSER_SCRIPTS = {"ieee_search.py", "patent_search.py", "patent_search_cnipa.py",
                    "scholar_search.py", "web_search.py", "web_ingest.py"}

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
PYTHON_BIN = os.environ.get("PYTHON_BIN") or sys.executable
WILSON_LIB_PATH = os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib"))


def _child_env(env_extra: dict | None = None) -> dict:
    """Subprocess env that forces the child Python to read/write UTF-8.

    Without this, on a Chinese Windows the child's stdout/stderr default to the
    GBK code page and .decode('utf-8') crashes on the first non-ASCII byte.
    """
    env = os.environ.copy()
    env["WILSON_LIB_PATH"] = WILSON_LIB_PATH
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return env


# Substrings that identify harmless noise lines from MinerU/torch on Windows.
# These are single-line warnings (not tracebacks) that can be dropped entirely.
_NOISE_LINE_MARKERS = (
    "pin_memory' argument is set as true but no accelerator",
)

# Substrings that identify the start of a traceback block to skip wholesale.
# The block ends when indentation returns to column 0.
_NOISE_TRACEBACK_MARKERS = (
    "_readerthread", "UnicodeDecodeError", "_bootstrap_inner",
    "buffer.append", "fh.read()", "<frozen codecs>",
)


def _filter_stderr(text: str) -> str:
    """Remove known harmless noise from child-process stderr."""
    lines = text.splitlines()
    out, skip = [], False
    for line in lines:
        if any(m in line for m in _NOISE_LINE_MARKERS):
            continue
        if any(m in line for m in _NOISE_TRACEBACK_MARKERS):
            skip = True
            continue
        if skip:
            if line.startswith(" ") or line.startswith("\t"):
                continue
            skip = False
        out.append(line)
    return "\n".join(out).strip()


async def _run(script: str, args: list[str], env_extra: dict | None = None, cdp_port: int | None = None) -> dict:
    """Run a script from scripts/ and return parsed JSON stdout."""
    extra = dict(env_extra) if env_extra else {}
    if cdp_port is not None and script in _BROWSER_SCRIPTS:
        extra["CDP_PORT"] = str(cdp_port)
    env = _child_env(extra)

    is_browser = script in _BROWSER_SCRIPTS
    timeout = _TIMEOUT_BROWSER if is_browser else _TIMEOUT_DEFAULT

    async def _exec() -> dict:
        proc = await asyncio.create_subprocess_exec(
            PYTHON_BIN,
            str(SCRIPTS_DIR / script),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise RuntimeError(f"{script} timed out after {timeout}s")

        # Always emit stderr so subprocess debug output is visible in pipeline logs
        err_text = stderr.decode("utf-8", "replace").strip()
        if err_text:
            err_text = _filter_stderr(err_text)
        if err_text:
            print(f"[{script}] stderr:\n{err_text[:2000]}", flush=True)

        if proc.returncode != 0:
            raise RuntimeError(f"{script} exited {proc.returncode}: {err_text[:500]}")

        out = stdout.decode("utf-8", "replace")
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"raw": out}

    if is_browser:
        return await _exec()
    return await _exec()


# ── Local search ────────────────────────────────────────────────────────────

async def local_search(keywords: list[str]) -> dict:
    return await _run("local_search.py", keywords + ["--json"])


# ── IEEE ─────────────────────────────────────────────────────────────────────

async def ieee_search_candidates(keywords: list[str], max_results: int, cdp_port: int | None = None) -> dict:
    return await _run("ieee_search.py", keywords + [f"--max={max_results}", "--search-only"], cdp_port=cdp_port)


async def ieee_download(dois: list[str], output_dir: str, cdp_port: int | None = None) -> dict:
    env = {"IEEE_PDF_SRC": output_dir} if output_dir and output_dir != "." else None
    return await _run("ieee_search.py", ["--doi"] + dois, env_extra=env, cdp_port=cdp_port)


def _build_frontmatter(pdf_path: "Path", md_text: str) -> str:
    """Minimal YAML frontmatter from the PDF filename (YYYY_Topic_..._DOI) + first H1.

    Matches the lightweight skeleton the pipeline already relied on; step8 agents
    fill the extended fields later.
    """
    import re
    import yaml

    stem = pdf_path.stem
    parts = stem.split("_", 2)
    year = int(parts[0]) if parts and parts[0].isdigit() else None
    topic = parts[1] if len(parts) > 1 else None
    doi_m = re.search(r"_(\d{7,10})$", stem)
    doi = doi_m.group(1) if doi_m else None
    title = stem
    for line in md_text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    fm: dict = {"title": title, "_frontmatter_status": "auto"}
    if year:
        fm["year"] = year
    if topic:
        fm["topic"] = topic
    if doi:
        fm["doi"] = doi

    # 从正文提取作者行（IEEE 格式：# 标题 → 作者行 → Abstract—）
    authors = _extract_authors_from_body(md_text)
    if authors:
        fm["authors"] = authors

    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n\n"


def _extract_authors_from_body(md_text: str) -> list[str]:
    """IEEE MD 正文解析：找 # 标题后第一个非空、非图片、非摘要行作为作者行。"""
    import re

    m = re.search(r"^#{1,3}[^\n]*\n+([^\n#!]{5,200})", md_text, re.MULTILINE)
    if not m:
        return []
    candidate = m.group(1).strip()
    if re.match(
        r"(?i)abstract|©|doi\s*:|received\s|manuscript\s|university|institute"
        r"|department|school|journal|proceedings|ieee\s+trans|vol\.\s*\d",
        candidate,
    ):
        return []
    # 去掉 IEEE 会员标注
    cleaned = re.sub(
        r",?\s*(?:Student\s+Member|Senior\s+Member|Fellow|Member),?\s*IEEE",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip().rstrip(",")
    # 按逗号或 "and" 分割
    raw_names = re.split(r",\s*(?:and\s+)?|\band\b", cleaned)
    authors = [n.strip() for n in raw_names if n.strip() and len(n.strip()) > 1]
    # 简单校验：每个名字至少含一个空格（名+姓），防止误识别单词段落
    authors = [a for a in authors if " " in a or (len(a) >= 3 and a[0].isupper())]
    return authors[:8]  # 最多保留 8 位作者


def _pdf_to_md(pdf_path: "Path", out_parent: "Path | None" = None, out_name: "str | None" = None) -> str:
    """Convert one PDF to MD using pymupdf4llm. Returns 'ok'/'skip'/'fail'.

    out_parent: parent directory for output (default: same directory as PDF)
    out_name:   stem name for output dir/file (default: pdf_path.stem)

    Images go to <out_dir>/images/ and are referenced with RELATIVE links
    (![](images/x.png)) so they render in the web viewer / Obsidian / any markdown
    tool and survive the staging→approved move.
    """
    import pymupdf4llm

    name = out_name or pdf_path.stem
    parent = out_parent or pdf_path.parent
    out_dir = parent / name
    md_path = out_dir / f"{name}.md"

    if md_path.exists():
        return "skip"

    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "images"
    img_dir.mkdir(exist_ok=True)

    md_text = pymupdf4llm.to_markdown(
        str(pdf_path),
        write_images=True,
        image_path=str(img_dir),
        image_format="png",
    )

    # pymupdf4llm bakes the absolute image_path into every ![](...) link; rewrite
    # that absolute prefix to a relative "images/" path so the links stay valid.
    abs_prefix = str(img_dir).replace("\\", "/").rstrip("/") + "/"
    md_text = md_text.replace(abs_prefix, "images/")

    md_path.write_text(_build_frontmatter(pdf_path, md_text) + md_text, encoding="utf-8")
    return "ok"


def _pdf_to_md_mineru(pdf_path: "Path", token: str,
                      out_parent: "Path | None" = None, out_name: "str | None" = None) -> str:
    """Convert one PDF via the MinerU cloud API. Returns 'ok'/'skip'/'fail'.

    Writes <out_parent>/<out_name>/<out_name>.md plus images/, using MinerU's
    native relative ![](images/<hash>.jpg) links (layout-aware figure extraction,
    far better than the raw page-image dump from pymupdf4llm). Defaults out_parent
    to the PDF's directory and out_name to a sanitized stem.
    """
    import re
    import shutil as _shutil
    import sys as _sys
    import tempfile as _tempfile
    from pathlib import Path as _Path

    if str(SCRIPTS_DIR) not in _sys.path:
        _sys.path.insert(0, str(SCRIPTS_DIR))
    from mineru_cloud import convert_pdf_cloud

    name = out_name or re.sub(r"[^A-Za-z0-9._-]", "_", pdf_path.stem)
    parent = out_parent or pdf_path.parent
    out_dir = parent / name
    md_path = out_dir / f"{name}.md"
    if md_path.exists():
        return "skip"

    # MinerU writes <tmp>/<safe_stem>/<safe_stem>.md + images/; relocate to out_dir
    # so we control the directory/file name (patents need <patent_num>/<patent_num>.md).
    tmp = _Path(_tempfile.mkdtemp(prefix="mineru_"))
    try:
        _name, status, _elapsed, error = convert_pdf_cloud(pdf_path, tmp, token=token)
        if status != "ok":
            print(f"[mineru-cloud] {pdf_path.name}: {error}", flush=True)
            return "fail"
        subs = [d for d in tmp.iterdir() if d.is_dir()]
        if not subs:
            print(f"[mineru-cloud] {pdf_path.name}: no output directory", flush=True)
            return "fail"
        if out_dir.exists():
            _shutil.rmtree(out_dir)
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        _shutil.move(str(subs[0]), str(out_dir))

        mds = list(out_dir.glob("*.md"))
        if not mds:
            print(f"[mineru-cloud] {pdf_path.name}: no md in output", flush=True)
            return "fail"
        if mds[0] != md_path:
            mds[0].rename(md_path)

        # MinerU output has no frontmatter; prepend the same skeleton as the fallback.
        text = md_path.read_text(encoding="utf-8")
        if not text.lstrip().startswith("---"):
            md_path.write_text(_build_frontmatter(pdf_path, text) + text, encoding="utf-8")
        return "ok"
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


async def ingest_pdf(output_dir: str) -> dict:
    """Convert PDFs in output_dir to MD. Runs in a thread pool (network/CPU-bound).

    Uses the MinerU cloud API when MINERU_API_TOKEN is set (layout-aware figure
    extraction); otherwise falls back to in-process pymupdf4llm. Either way images
    land in <stem>/images/ and are referenced with relative ![](images/..) links.
    """
    import asyncio as _asyncio
    from pathlib import Path as _Path

    pdf_files = list(_Path(output_dir).rglob("*.pdf")) if output_dir and output_dir != "." else []
    if not pdf_files:
        return {"ok": 0, "skip": 0, "fail": 0}

    token = os.environ.get("MINERU_API_TOKEN", "")
    engine = "mineru-cloud" if token else "pymupdf4llm"
    convert = (lambda p: _pdf_to_md_mineru(p, token)) if token else _pdf_to_md

    sem = _asyncio.Semaphore(4)

    async def _bounded(pdf: "_Path") -> str:
        async with sem:
            try:
                return await _asyncio.to_thread(convert, pdf)
            except Exception as e:
                print(f"[ingest_pdf/{engine}] {pdf.name}: {e}", flush=True)
                return "fail"

    results = await _asyncio.gather(*[_bounded(p) for p in pdf_files])
    counts: dict[str, int] = {"ok": 0, "skip": 0, "fail": 0}
    for r in results:
        counts[r] = counts.get(r, 0) + 1
    print(f"[ingest_pdf] engine={engine} {counts}", flush=True)
    return counts


# ── Patents ───────────────────────────────────────────────────────────────────

async def patent_search_candidates(keywords: list[str], max_results: int, cdp_port: int | None = None) -> dict:
    return await _run(
        "patent_search.py",
        keywords + [f"--max={max_results}", "--search-only", "--json"],
        cdp_port=cdp_port,
    )


async def patent_download(patent_numbers: list[str], output_dir: str, cdp_port: int | None = None) -> dict:
    return await _run(
        "patent_search.py",
        ["--patent-numbers"] + patent_numbers + [f"--output-dir={output_dir}"],
        cdp_port=cdp_port,
    )


async def patent_convert(staging_dir: str) -> dict:
    """Convert PDFs in staging_dir → MDs under staging_dir/../patent_md/.

    Output: patent_md/<patent_num>/<patent_num>.md  (patent_num extracted from filename).
    Uses the MinerU cloud API when MINERU_API_TOKEN is set; otherwise falls back to
    in-process pymupdf4llm. Either way images use relative ![](images/..) links.
    """
    import asyncio as _asyncio
    from pathlib import Path as _Path

    pdf_files = list(_Path(staging_dir).rglob("*.pdf")) if staging_dir and staging_dir != "." else []
    if not pdf_files:
        return {"ok": 0, "skip": 0, "fail": 0, "new_patents": []}

    patent_md_dir = _Path(staging_dir).parent / "patent_md"
    patent_md_dir.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("MINERU_API_TOKEN", "")
    engine = "mineru-cloud" if token else "pymupdf4llm"

    def _convert(pdf: "_Path") -> str:
        # "CN112928907B - [] CN112928907B.pdf" → patent_num = "CN112928907B"
        patent_num = pdf.stem.split(" - ")[0].strip() if " - " in pdf.stem else pdf.stem
        if token:
            return _pdf_to_md_mineru(pdf, token, patent_md_dir, patent_num)
        return _pdf_to_md(pdf, patent_md_dir, patent_num)

    sem = _asyncio.Semaphore(4)

    async def _bounded(pdf: "_Path") -> str:
        async with sem:
            try:
                return await _asyncio.to_thread(_convert, pdf)
            except Exception as e:
                print(f"[patent_convert/{engine}] {pdf.name}: {e}", flush=True)
                return "fail"

    results = await _asyncio.gather(*[_bounded(p) for p in pdf_files])
    counts: dict[str, int] = {"ok": 0, "skip": 0, "fail": 0}
    for r in results:
        counts[r] = counts.get(r, 0) + 1
    print(f"[patent_convert] engine={engine} {counts}", flush=True)
    return {**counts, "new_patents": []}


# ── Web ───────────────────────────────────────────────────────────────────────

async def web_search(keywords: list[str], max_results: int, cdp_port: int | None = None) -> dict:
    return await _run("web_search.py", [" ".join(keywords), f"--max={max_results}", "--json"], cdp_port=cdp_port)


async def web_ingest(urls: list[str], topic: str, output_dir: str, cdp_port: int | None = None) -> dict:
    return await _run("web_ingest.py", urls + ["--topic", topic, f"--output-dir={output_dir}"], cdp_port=cdp_port)


# ── Gate & reporting ──────────────────────────────────────────────────────────

async def check_report(report_path: str, mode: str = "full",
                       env_extra: dict | None = None) -> tuple[int, str]:
    """Returns (exit_code, combined_output).

    mode:
      full          — check_report.py <report_path>
      papers        — check_report.py --papers [dir]
      papers-brief  — check_report.py --papers-brief [dir]
      lint-papers   — check_report.py --lint-papers [dir]  (no path = whole vault)
      lint-patents  — check_report.py --lint-patents       (no path arg)

    env_extra: extra env vars for the child (e.g. EXTRA_SEARCH_PATHS so staging
    figures/wikilinks resolve while a report is still pre-approval).
    """
    script = str(SCRIPTS_DIR / "check_report.py")

    if mode == "full":
        args = [report_path] if report_path else ["--all"]
    elif mode == "lint-patents":
        # flag only, no positional argument
        args = ["--lint-patents"]
    else:
        # papers / papers-brief / lint-papers — optional dir arg
        args = [f"--{mode}"]
        if report_path:
            args.append(report_path)

    proc = await asyncio.create_subprocess_exec(
        PYTHON_BIN, script, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_child_env(env_extra),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_DEFAULT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return 1, f"check_report.py timed out after {_TIMEOUT_DEFAULT}s"
    return proc.returncode, stdout.decode("utf-8", "replace") + stderr.decode("utf-8", "replace")


async def fix_citations(report_path: str) -> dict:
    return await _run("fix_report_citations.py", [report_path])


async def export_report(report_path: str) -> dict:
    return await _run("export_report.py", [report_path])
