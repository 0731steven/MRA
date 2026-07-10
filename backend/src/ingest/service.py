"""Batch PDF ingest service.

Flow per file:
  queued → converting (MinerU cloud API) → classifying (categorize) → done / failed

Jobs are in-memory; they don't need to survive restarts.
"""
import asyncio
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, Optional

# Import helpers directly from scripts package
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from mineru_cloud import convert_pdf_cloud  # noqa: E402
from paper_manager import categorize  # noqa: E402

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ingest")
_jobs: dict[str, "Job"] = {}


@dataclass
class FileStatus:
    filename: str
    status: Literal["queued", "converting", "classifying", "done", "failed"] = "queued"
    category: str = ""
    target_path: str = ""
    error: str = ""
    elapsed: float = 0.0
    poll_count: int = 0
    max_polls: int = 0


@dataclass
class Job:
    job_id: str
    files: list[FileStatus]
    created_at: float = field(default_factory=time.time)


def _extract_title_and_keywords(md_path: pathlib.Path) -> tuple[str, str]:
    """Return (title, index_terms) from a MinerU-converted MD.

    Title  — first # heading (or file stem as fallback).
    Keywords — text following an "Index Terms" / "Keywords" line, which IEEE
               papers always include; used as extra_keywords for categorize().
    """
    title = md_path.stem
    keywords = ""
    try:
        lines = md_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return title, keywords

    _KW_RE = re.compile(
        r"^(?:index\s+terms?|keywords?)\s*[:\-—]?\s*(.*)",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines[:300]):
        stripped = line.strip()
        # pick up title from first heading
        if not title or title == md_path.stem:
            m = re.match(r"^#{1,3}\s+(.+)", stripped)
            if m:
                title = m.group(1).strip()
        # pick up index terms
        if not keywords:
            km = _KW_RE.match(stripped)
            if km:
                inline = km.group(1).strip()
                if inline:
                    keywords = inline
                elif i + 1 < len(lines):
                    keywords = lines[i + 1].strip()

    return title, keywords


def _process_one(pdf_bytes: bytes, filename: str, fstat: FileStatus) -> None:
    """Blocking: convert → classify → move to wilson_lib. Runs in thread pool."""
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", pathlib.Path(filename).stem)
    wilson_lib = pathlib.Path(
        os.environ.get("WILSON_LIB_PATH", str(pathlib.Path.home() / "Documents" / "wilson_lib"))
    )

    with tempfile.TemporaryDirectory(prefix="ingest_") as tmpdir:
        tmp = pathlib.Path(tmpdir)
        pdf_path = tmp / f"{safe_stem}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        out_dir = tmp / "out"
        out_dir.mkdir()

        fstat.status = "converting"
        _, status, elapsed, err = convert_pdf_cloud(
            pdf_path, out_dir,
            on_poll=lambda n, m: setattr(fstat, "poll_count", n) or setattr(fstat, "max_polls", m),
        )
        fstat.elapsed = round(elapsed, 1)

        if status != "ok":
            fstat.status = "failed"
            fstat.error = err or "conversion failed"
            return

        md_path = out_dir / safe_stem / f"{safe_stem}.md"
        if not md_path.exists():
            fstat.status = "failed"
            fstat.error = "output MD not found in result zip"
            return

        fstat.status = "classifying"
        title, keywords = _extract_title_and_keywords(md_path)
        category = categorize(title, extra_keywords=keywords or None, filename=filename)
        fstat.category = category

        if category == "Patent":
            target_dir = wilson_lib / "patent_md" / safe_stem
        else:
            target_dir = wilson_lib / "ieee_paper_md" / category / safe_stem

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(out_dir / safe_stem), str(target_dir))
        (target_dir / f"{safe_stem}.pdf").write_bytes(pdf_bytes)

        fstat.target_path = str(target_dir / f"{safe_stem}.md")
        fstat.status = "done"


async def start_job(files: list[tuple[str, bytes]]) -> str:
    """Create job, start background processing, return job_id."""
    job_id = uuid.uuid4().hex[:8]
    statuses = [FileStatus(filename=name) for name, _ in files]
    _jobs[job_id] = Job(job_id=job_id, files=statuses)
    asyncio.create_task(_run_all(files, statuses))
    return job_id


async def _run_all(files: list[tuple[str, bytes]], statuses: list[FileStatus]) -> None:
    loop = asyncio.get_running_loop()
    await asyncio.gather(
        *[
            loop.run_in_executor(_executor, _process_one, pdf_bytes, name, fstat)
            for (name, pdf_bytes), fstat in zip(files, statuses)
        ],
        return_exceptions=True,
    )


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)
