"""Document review HTTP routes."""
import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_db
from ..db.models import PendingDocument, ResearchTask, Question, User
from ..auth.handler import get_current_user
from . import service

router = APIRouter()


def _find_staging_md(staging_path: str) -> Path | None:
    """Return the .md file for a pending document's staging path."""
    p = Path(staging_path)
    # staging_path may be the directory or the file itself
    if p.suffix == ".md" and p.exists():
        return p
    if p.is_dir():
        mds = list(p.glob("*.md"))
        if mds:
            return mds[0]
    # Try with .md extension
    md = Path(str(p) + ".md")
    if md.exists():
        return md
    return None


def _parse_frontmatter(text: str) -> dict:
    """Extract key fields from YAML frontmatter."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end]
    result = {}
    for line in fm.splitlines():
        m = re.match(r'^(\w+):\s*(.+)$', line.strip())
        if m:
            result[m.group(1)] = m.group(2).strip().strip('"\'')
    return result


def _doc_meta(d: PendingDocument) -> dict:
    """Read frontmatter from the staging MD and return useful fields."""
    md_path = _find_staging_md(d.staging_path)
    if not md_path:
        return {}
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        fm = _parse_frontmatter(text)
        return {
            "authors": fm.get("authors") or fm.get("author") or fm.get("inventors") or "",
            "year": fm.get("year") or fm.get("published_year") or fm.get("date", "")[:4],
            "venue": fm.get("venue") or fm.get("journal") or fm.get("conference") or fm.get("publisher") or "",
            "doi": fm.get("doi") or fm.get("DOI") or "",
            "abstract": fm.get("abstract") or "",
            "ipc": fm.get("ipc") or fm.get("IPC") or "",
            "core_innovation": fm.get("core_innovation") or "",
        }
    except Exception:
        return {}


async def _load_pending(doc_id: int, user: User, db: AsyncSession) -> PendingDocument:
    result = await db.execute(select(PendingDocument).where(PendingDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Pending document not found")
    if doc.status != "pending":
        raise HTTPException(status_code=409, detail=f"Document already {doc.status}")
    # Non-admin: verify the doc belongs to a task created by this user
    if user.role != "admin":
        task_result = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == doc.task_id, Question.user_id == user.id)
        )
        if task_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your document")
    return doc


@router.get("/pending-docs/count")
async def count_pending(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).select_from(PendingDocument)
        .join(ResearchTask, PendingDocument.task_id == ResearchTask.id)
        .join(Question, ResearchTask.question_id == Question.id)
        .where(PendingDocument.status == "pending", Question.user_id == user.id)
    )
    return {"count": result.scalar() or 0}


@router.get("/pending-docs")
async def list_pending(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(
            select(PendingDocument, Question.raw_text)
            .join(ResearchTask, PendingDocument.task_id == ResearchTask.id)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(PendingDocument.status == "pending")
            .order_by(PendingDocument.created_at.desc())
        )
    else:
        result = await db.execute(
            select(PendingDocument, Question.raw_text)
            .join(ResearchTask, PendingDocument.task_id == ResearchTask.id)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(PendingDocument.status == "pending", Question.user_id == user.id)
            .order_by(PendingDocument.created_at.desc())
        )
    return [
        {
            "id": d.id,
            "task_id": d.task_id,
            "question_text": raw_text,
            "source": d.source,
            "title": d.title,
            "staging_path": d.staging_path,
            "target_path": d.target_path,
            "status": d.status,
            "created_at": d.created_at,
            **_doc_meta(d),
        }
        for d, raw_text in result.all()
    ]


@router.get("/pending-docs/{doc_id}/preview", response_class=PlainTextResponse)
async def preview_doc(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return raw markdown content of the staging file for in-drawer preview."""
    result = await db.execute(select(PendingDocument).where(PendingDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    if user.role != "admin":
        task_result = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == doc.task_id, Question.user_id == user.id)
        )
        if task_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your document")
    md_path = _find_staging_md(doc.staging_path)
    if not md_path:
        raise HTTPException(status_code=404, detail="Staging file not found")
    return PlainTextResponse(
        md_path.read_text(encoding="utf-8", errors="ignore"),
        headers={"X-File-Dir": md_path.parent.as_posix()},
    )


@router.post("/pending-docs/{doc_id}/approve")
async def approve_doc(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _load_pending(doc_id, user, db)
    await service.approve_document(doc, user.id, db)
    return {"status": "approved"}


@router.post("/pending-docs/{doc_id}/reject")
async def reject_doc(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _load_pending(doc_id, user, db)
    await service.reject_document(doc, user.id, db)
    return {"status": "rejected"}


@router.post("/pending-docs/batch")
async def batch_review(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject many docs in one call.

    Body: ``{"action": "approve" | "reject", "ids": [1, 2, 3]}``.
    """
    action = payload.get("action")
    ids = payload.get("ids") or []
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    processed: list[int] = []
    skipped: list[int] = []
    for doc_id in ids:
        result = await db.execute(select(PendingDocument).where(PendingDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if doc is None or doc.status != "pending":
            skipped.append(doc_id)
            continue
        # Permission check
        if user.role != "admin":
            task_result = await db.execute(
                select(ResearchTask)
                .join(Question, ResearchTask.question_id == Question.id)
                .where(ResearchTask.id == doc.task_id, Question.user_id == user.id)
            )
            if task_result.scalar_one_or_none() is None:
                skipped.append(doc_id)
                continue
        if action == "approve":
            await service.approve_document(doc, user.id, db)
        else:
            await service.reject_document(doc, user.id, db)
        processed.append(doc_id)

    return {"action": action, "processed": processed, "skipped": skipped}
