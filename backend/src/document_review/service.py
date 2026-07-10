"""Document review service — approve / reject / auto-approve logic.

Lifecycle (per CLAUDE.md「文档审核入库机制」):
  pending  → approved  : staging file moved into wilson_lib (target_path)
  pending  → rejected  : staging file deleted
  pending  → approved (auto) : >EXPIRE_DAYS unreviewed → auto-approved into wilson_lib
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PendingDocument, User, Question, ResearchTask

WILSON_LIB_PATH = Path(os.environ.get("WILSON_LIB_PATH", str(Path.home() / "Documents" / "wilson_lib")))
EXPIRE_DAYS = int(os.environ.get("PENDING_DOC_EXPIRE_DAYS", "30"))
FEISHU_ENABLED = os.environ.get("FEISHU_ENABLED", "false").lower() == "true"


def _find_pdf_in_staging(stem: str, src: Path) -> Path | None:
    """Find a PDF in the staging task root that fuzzy-matches stem.

    IEEE layout:  staging/task_N/ieee/<topic>/<stem>.pdf   (src.parent)
    Patent layout: staging/task_N/patent/<stem>.pdf        (src.parent.parent.parent)

    The MD directory name has special chars sanitised to '_', so exact match
    often fails. Strategy: exact → DOI suffix (last 7-10 digits) → 30-char prefix.
    Falls back to searching the whole staging task root (rglob) for patents whose
    PDF lives in a sibling directory of the MD tree.
    """
    import re
    stem_lower = stem.lower()
    doi_m = re.search(r'_(\d{7,10})$', stem)
    doi = doi_m.group(1) if doi_m else None
    # patent number prefix: e.g. US8093951
    pat_m = re.match(r'^([A-Za-z]{2}\d{6,}[A-Za-z]?\d?)', stem, re.IGNORECASE)
    pat_num = pat_m.group(1).upper() if pat_m else None
    prefix = stem_lower[:30]

    # Determine the staging task root (staging/task_N/)
    # src is the MD dir: staging/task_N/patent_md/patent/<stem>/  or
    #                    staging/task_N/ieee/<topic>/<stem>/
    # Walk up until we find a dir named "task_*"
    task_root: Path | None = None
    p = src
    for _ in range(6):
        if p.name.startswith("task_"):
            task_root = p
            break
        p = p.parent

    search_roots = [src.parent, src.parent.parent]
    if task_root and task_root not in search_roots:
        search_roots.append(task_root)

    for root in search_roots:
        if not root.exists():
            continue
        doi_hit = prefix_hit = pat_hit = None
        iterator = root.rglob("*.pdf") if root == task_root else root.iterdir()
        for f in iterator:
            if f.suffix.lower() != ".pdf":
                continue
            fs = f.stem.lower()
            if fs == stem_lower:
                return f
            if doi and doi_hit is None and fs.endswith(f"_{doi}"):
                doi_hit = f
            if pat_num and pat_hit is None and f.stem.upper().startswith(pat_num):
                pat_hit = f
            if prefix_hit is None and fs.startswith(prefix):
                prefix_hit = f
        hit = doi_hit or pat_hit or prefix_hit
        if hit is not None:
            return hit
    return None


def _move_pdf_alongside_md(src: Path, dst: Path) -> None:
    """把 staging 里的 PDF 一起移到 vault 目标目录。

    IEEE:   PDF 与 MD 目录同级 (src.parent/<stem>.pdf)
    Patent: PDF 在 staging/task_N/patent/，MD 在 staging/task_N/patent_md/...
    用模糊匹配处理文件名特殊字符被替换的情况。
    """
    stem = src.stem if src.is_file() else src.name
    dst_dir = dst if dst.is_dir() else dst.parent

    pdf = _find_pdf_in_staging(stem, src)
    if pdf is not None:
        pdf_dst = dst_dir / pdf.name
        if not pdf_dst.exists():
            try:
                shutil.move(str(pdf), str(pdf_dst))
            except OSError:
                pass


def _unlink_quietly(path: Path) -> None:
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


async def approve_document(doc: PendingDocument, admin_id: int, db: AsyncSession) -> None:
    """Move the staging file/directory into the vault and mark the record approved.

    staging_path may be a file (IEEE / Web MD) or a directory (patent MD dir from MinerU).
    target_path is always relative to WILSON_LIB_PATH.
    """
    src = Path(doc.staging_path)
    dst = WILSON_LIB_PATH / doc.target_path

    if src.exists():
        if src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    # Best-effort: copy matching PDF from download dirs into the vault alongside the MD
    _move_pdf_alongside_md(src, dst)

    doc.status = "approved"
    doc.reviewed_by = admin_id
    doc.reviewed_at = datetime.now(timezone.utc)
    await db.commit()


async def reject_document(doc: PendingDocument, admin_id: int, db: AsyncSession) -> None:
    """Mark the document rejected. Staging file is left in place until the report is deleted,
    so existing report wikilinks remain accessible. The file will be cleaned up by delete_report."""
    doc.status = "rejected"
    doc.reviewed_by = admin_id
    doc.reviewed_at = datetime.now(timezone.utc)
    await db.commit()


async def cleanup_expired_documents(db: AsyncSession, now: datetime | None = None) -> int:
    """Auto-approve pending docs older than ``EXPIRE_DAYS`` by moving them into the vault.

    Returns the number of documents auto-approved (0 if none).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=EXPIRE_DAYS)

    result = await db.execute(
        select(PendingDocument).where(
            PendingDocument.status == "pending",
            PendingDocument.created_at < cutoff,
        )
    )
    stale = result.scalars().all()
    for doc in stale:
        src = Path(doc.staging_path)
        dst = WILSON_LIB_PATH / doc.target_path
        if src.exists():
            try:
                if src.is_dir():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(src), str(dst))
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                _move_pdf_alongside_md(src, dst)
            except OSError as e:
                print(f"[cleanup] auto-approve move failed for {doc.id}: {e}")
        doc.status = "approved"
        doc.reviewed_at = now

    if stale:
        await db.commit()
    return len(stale)


async def notify_admins_new_pending(task_id: int, count: int, db: AsyncSession) -> None:
    """Best-effort Feishu notification to all admins about new docs awaiting review.

    No-op when Feishu is disabled or there are no admins. Never raises — review
    notification is advisory; the Web 待审列表 is the source of truth.
    """
    if not FEISHU_ENABLED or count <= 0:
        return

    # Resolve the asking user's question text for context.
    q_result = await db.execute(
        select(Question.raw_text)
        .join(ResearchTask, Question.id == ResearchTask.question_id)
        .where(ResearchTask.id == task_id)
    )
    row = q_result.first()
    question_text = row[0] if row else ""

    admins_result = await db.execute(select(User.feishu_user_id).where(User.role == "admin"))
    admin_ids = [r[0] for r in admins_result.all() if r[0]]
    if not admin_ids:
        return

    text = (
        f"📥 有 {count} 篇远程文档待审核入库\n"
        f"来源问题：{question_text}\n"
        f"请到 Web 审核页处理（批准入库 / 拒绝丢弃）。"
    )

    try:
        import json as _json
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        client = (
            lark.Client.builder()
            .app_id(os.environ.get("FEISHU_APP_ID", ""))
            .app_secret(os.environ.get("FEISHU_APP_SECRET", ""))
            .build()
        )
        for uid in admin_ids:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(uid)
                    .msg_type("text")
                    .content(_json.dumps({"text": text}))
                    .build()
                )
                .build()
            )
            await client.im.v1.message.acreate(req)
    except Exception as exc:  # noqa: BLE001 — advisory notification, never fatal
        print(f"[DocumentReview] admin notify failed: {exc}")
