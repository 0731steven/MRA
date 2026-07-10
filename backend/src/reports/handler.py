import os
import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text

from ..db.session import get_db
from ..db.models import Report, ResearchTask, Question, User, GateResult, PendingDocument, ReportChatMessage
from ..auth.handler import get_current_user

router = APIRouter()

WILSON_LIB = Path(os.environ.get("COMPANY_LIB_PATH", os.environ.get("WILSON_LIB_PATH", str(Path.home() / "company_lib"))))
QA_DIR = WILSON_LIB / "wiki" / "qa"


def _find_qa_for_report(vault_path: str) -> list[Path]:
    """Find wiki/qa/*.md files whose frontmatter report_path matches vault_path."""
    if not QA_DIR.exists():
        return []
    matches: list[Path] = []
    # Normalise to forward-slash relative path for comparison
    norm = vault_path.replace("\\", "/").lstrip("/")
    # Also prepare the bare filename for suffix matching
    norm_name = Path(norm).name
    for qa in QA_DIR.glob("*.md"):
        try:
            text = qa.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'^report_path:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
            if not m:
                continue
            stored = m.group(1).replace("\\", "/").lstrip("/")
            # Match if stored path ends with our norm (handles absolute vs relative)
            if stored == norm or stored.endswith("/" + norm) or norm.endswith("/" + stored):
                matches.append(qa)
            elif Path(stored).name == norm_name:
                matches.append(qa)
        except Exception:
            pass
    return matches


@router.get("/reports")
async def list_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "admin":
        result = await db.execute(
            select(Report).order_by(Report.created_at.desc()).limit(50)
        )
    else:
        result = await db.execute(
            select(Report)
            .join(ResearchTask, Report.task_id == ResearchTask.id)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(Question.user_id == user.id)
            .order_by(Report.created_at.desc())
            .limit(50)
        )
    return [
        {
            "id": r.id,
            "vault_path": r.vault_path,
            "summary_text": r.summary_text,
            "report_type": r.report_type,
            "eval_scores": json.loads(r.eval_scores_json) if r.eval_scores_json else {},
            "created_at": r.created_at,
        }
        for r in result.scalars().all()
    ]


@router.get("/reports/{report_id}")
async def get_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if user.role != "admin":
        check = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == report.task_id, Question.user_id == user.id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your report")

    # Read report file content
    content = ""
    if report.vault_path:
        try:
            rpath = Path(report.vault_path)
            if not rpath.is_absolute():
                rpath = WILSON_LIB / report.vault_path
            content = rpath.read_text(encoding="utf-8")
        except Exception:
            content = ""

    return {
        "id": report.id,
        "vault_path": report.vault_path,
        "summary_text": report.summary_text,
        "citations_json": report.citations_json,
        "report_type": report.report_type,
        "research_params": json.loads(report.research_params_json) if report.research_params_json else {},
        "me_data_stats": json.loads(report.me_data_stats_json) if report.me_data_stats_json else {},
        "coverage": json.loads(report.coverage_json) if report.coverage_json else [],
        "qc_warnings": json.loads(report.qc_warnings_json) if report.qc_warnings_json else [],
        "eval_scores": json.loads(report.eval_scores_json) if report.eval_scores_json else {},
        "content": content,
        "created_at": report.created_at,
    }


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else WILSON_LIB / path


def _pending_docs_for_report(report: Report, pending_docs: list[PendingDocument]) -> list[dict]:
    items = []
    for doc in pending_docs:
        staging = Path(doc.staging_path)
        target = _resolve(doc.target_path)
        items.append({
            "id": doc.id,
            "source": doc.source,
            "title": doc.title,
            "status": doc.status,
            "will_delete_staging": doc.status != "approved" and staging.exists(),
            "will_delete_target": False,  # approved docs stay in shared vault
            "staging_exists": staging.exists(),
            "target_exists": target.exists(),
            "staging_path": doc.staging_path,
            "target_path": doc.target_path,
        })
    return items


@router.get("/reports/{report_id}/delete-preview")
async def delete_preview(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a list of all files that would be deleted with this report."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if user.role != "admin":
        check = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == report.task_id, Question.user_id == user.id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your report")

    pd_result = await db.execute(
        select(PendingDocument).where(PendingDocument.task_id == report.task_id)
    )
    pending_docs = pd_result.scalars().all()

    report_path = _resolve(report.vault_path) if report.vault_path else None
    qa_files = _find_qa_for_report(report.vault_path) if report.vault_path else []

    return {
        "report": {
            "path": report.vault_path,
            "exists": report_path.exists() if report_path else False,
        },
        "qa_files": [str(p.relative_to(WILSON_LIB)) for p in qa_files],
        "documents": _pending_docs_for_report(report, pending_docs),
    }


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if user.role != "admin":
        check = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == report.task_id, Question.user_id == user.id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your report")

    deleted_files: list[str] = []
    failed_files: list[str] = []

    def _rm(path: Path) -> None:
        try:
            if path.is_dir():
                shutil.rmtree(path)
                deleted_files.append(str(path))
            elif path.exists():
                path.unlink()
                deleted_files.append(str(path))
            # silently skip non-existent paths
        except Exception as e:
            failed_files.append(f"{path}: {e}")

    # 1. Delete report MD file
    if report.vault_path:
        _rm(_resolve(report.vault_path))

    # 2. Delete qa archive files linked to this report
    for qa in _find_qa_for_report(report.vault_path or ""):
        _rm(qa)

    # 3. Delete staging root dir (covers all pending/rejected docs in one shot).
    #    approved docs have been moved to the shared vault — do NOT delete them.
    task_staging = WILSON_LIB / "staging" / f"task_{report.task_id}"
    _rm(task_staging)

    # 5. DB cleanup — raw SQL in FK-safe order.
    #    A question may have multiple research_tasks (retries / recovery), so we
    #    must wipe ALL tasks for the question, not just the one tied to this report.
    task_result = await db.execute(
        select(ResearchTask.question_id).where(ResearchTask.id == report.task_id)
    )
    row = task_result.first()
    question_id = row[0] if row else None

    # Collect all task ids for this question so we can delete their children too
    if question_id is not None:
        all_tasks_result = await db.execute(
            select(ResearchTask.id).where(ResearchTask.question_id == question_id)
        )
        all_task_ids = [r[0] for r in all_tasks_result.fetchall()]
    else:
        all_task_ids = [report.task_id]

    for tid in all_task_ids:
        # report_chat_messages references reports, delete per-report first
        reps_result = await db.execute(
            select(Report.id).where(Report.task_id == tid)
        )
        for (rid,) in reps_result.fetchall():
            await db.execute(text("DELETE FROM report_chat_messages WHERE report_id = :rid"), {"rid": rid})
        await db.execute(text("DELETE FROM reports WHERE task_id = :tid"), {"tid": tid})
        await db.execute(text("DELETE FROM pending_documents WHERE task_id = :tid"), {"tid": tid})
        await db.execute(text("DELETE FROM gate_results WHERE task_id = :tid"), {"tid": tid})
        await db.execute(text("DELETE FROM research_tasks WHERE id = :tid"), {"tid": tid})

    if question_id is not None:
        await db.execute(text("DELETE FROM questions WHERE id = :qid"), {"qid": question_id})

    await db.commit()

    return {
        "deleted": report_id,
        "deleted_files": deleted_files,
        "failed_files": failed_files,
    }


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if user.role != "admin":
        check = await db.execute(
            select(ResearchTask)
            .join(Question, ResearchTask.question_id == Question.id)
            .where(ResearchTask.id == report.task_id, Question.user_id == user.id)
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Not your report")

    if not report.vault_path:
        raise HTTPException(status_code=404, detail="Report file not found")

    rpath = Path(report.vault_path)
    if not rpath.is_absolute():
        rpath = WILSON_LIB / report.vault_path
    if not rpath.exists():
        raise HTTPException(status_code=404, detail="Report file missing on disk")

    # Try to use export_report.py to build a zip; fall back to raw MD
    try:
        from ..integrations import cad_tools
        result_data = await cad_tools.export_report(str(rpath))
        zip_path = result_data.get("zip_path", "")
        if zip_path and Path(zip_path).exists():
            return FileResponse(zip_path, media_type="application/zip",
                                filename=Path(zip_path).name)
    except Exception:
        pass

    return FileResponse(str(rpath), media_type="text/markdown", filename=rpath.name)
