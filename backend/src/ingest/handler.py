"""Batch PDF ingest API routes."""
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth.handler import get_current_user
from ..db.models import User
from . import service

router = APIRouter()

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB per file


def _require_token() -> None:
    if not os.environ.get("MINERU_API_TOKEN"):
        raise HTTPException(503, "MINERU_API_TOKEN not configured on the server")


@router.post("/ingest/batch")
async def upload_batch(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    _require_token()

    if not files:
        raise HTTPException(400, "No files provided")

    file_data: list[tuple[str, bytes]] = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"{f.filename!r} is not a PDF file")
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{f.filename} exceeds 100 MB limit")
        file_data.append((f.filename, data))

    job_id = await service.start_job(file_data)
    return {"job_id": job_id, "total": len(file_data)}


@router.get("/ingest/jobs/{job_id}")
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")

    job = service.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    done = sum(1 for f in job.files if f.status in ("done", "failed"))
    return {
        "job_id": job_id,
        "total": len(job.files),
        "done": done,
        "files": [
            {
                "filename": f.filename,
                "status": f.status,
                "category": f.category,
                "target_path": f.target_path,
                "error": f.error,
                "elapsed": f.elapsed,
                "poll_count": f.poll_count,
                "max_polls": f.max_polls,
            }
            for f in job.files
        ],
    }
