"""Tests for the document review service (approve / reject / expire)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.db.session import AsyncSessionLocal, engine, Base
from src.db.models import User, Question, ResearchTask, PendingDocument
from src.document_review import service


@pytest.fixture(autouse=True)
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_task(db) -> tuple[int, int]:
    """Insert admin User + Question + ResearchTask. Returns (admin_id, task_id)."""
    admin = User(feishu_user_id="ou_admin_001", name="Admin", role="admin")
    db.add(admin)
    await db.flush()

    question = Question(user_id=admin.id, tier="normal", raw_text="LDO PSRR", status="running")
    db.add(question)
    await db.flush()

    task = ResearchTask(question_id=question.id, status="step8_gate")
    db.add(task)
    await db.flush()
    return admin.id, task.id


def _staging_file(task_id: int, name: str) -> Path:
    """Create a real staging file under WILSON_LIB_PATH/staging and return its path."""
    wilson = Path(os.environ["WILSON_LIB_PATH"])
    staging = wilson / "staging" / f"task_{task_id}" / "ieee"
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / name
    f.write_text("# paper md\n", encoding="utf-8")
    return f


async def test_approve_moves_file_into_vault() -> None:
    async with AsyncSessionLocal() as db:
        admin_id, task_id = await _seed_task(db)
        src = _staging_file(task_id, "paper1.md")
        doc = PendingDocument(
            task_id=task_id, source="ieee", title="Paper 1",
            staging_path=str(src), target_path="ieee_paper_md/paper1.md", status="pending",
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id

        await service.approve_document(doc, admin_id, db)

    wilson = Path(os.environ["WILSON_LIB_PATH"])
    dst = wilson / "ieee_paper_md" / "paper1.md"
    assert dst.exists(), "approved file was not moved into the vault"
    assert not src.exists(), "staging file should have been moved (not copied)"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        row = (await db.execute(select(PendingDocument).where(PendingDocument.id == doc_id))).scalar_one()
        assert row.status == "approved"
        assert row.reviewed_by == admin_id
        assert row.reviewed_at is not None


async def test_reject_deletes_staging_file() -> None:
    async with AsyncSessionLocal() as db:
        admin_id, task_id = await _seed_task(db)
        src = _staging_file(task_id, "paper2.md")
        doc = PendingDocument(
            task_id=task_id, source="ieee", title="Paper 2",
            staging_path=str(src), target_path="ieee_paper_md/paper2.md", status="pending",
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id

        await service.reject_document(doc, admin_id, db)

    assert not src.exists(), "rejected staging file should be deleted"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        row = (await db.execute(select(PendingDocument).where(PendingDocument.id == doc_id))).scalar_one()
        assert row.status == "rejected"
        assert row.reviewed_by == admin_id


async def test_cleanup_expires_only_old_pending() -> None:
    async with AsyncSessionLocal() as db:
        _, task_id = await _seed_task(db)
        old_src = _staging_file(task_id, "old.md")
        new_src = _staging_file(task_id, "new.md")

        # Naive timestamps to keep SQLite string comparison consistent.
        now = datetime(2026, 5, 20)
        old_doc = PendingDocument(
            task_id=task_id, source="ieee", title="Old",
            staging_path=str(old_src), target_path="ieee_paper_md/old.md",
            status="pending", created_at=now - timedelta(days=45),
        )
        new_doc = PendingDocument(
            task_id=task_id, source="ieee", title="New",
            staging_path=str(new_src), target_path="ieee_paper_md/new.md",
            status="pending", created_at=now - timedelta(days=2),
        )
        db.add_all([old_doc, new_doc])
        await db.commit()
        old_id, new_id = old_doc.id, new_doc.id

        expired = await service.cleanup_expired_documents(db, now=now)

    assert expired == 1
    assert not old_src.exists(), "expired staging file should be deleted"
    assert new_src.exists(), "recent staging file should be untouched"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        old_row = (await db.execute(select(PendingDocument).where(PendingDocument.id == old_id))).scalar_one()
        new_row = (await db.execute(select(PendingDocument).where(PendingDocument.id == new_id))).scalar_one()
        assert old_row.status == "expired"
        assert new_row.status == "pending"


async def test_approve_tolerates_missing_source() -> None:
    """A missing staging file must not strand the record in 'pending'."""
    async with AsyncSessionLocal() as db:
        admin_id, task_id = await _seed_task(db)
        doc = PendingDocument(
            task_id=task_id, source="patent", title="Gone",
            staging_path=str(Path(os.environ["WILSON_LIB_PATH"]) / "staging" / "nope.md"),
            target_path="patent_md/gone.md", status="pending",
        )
        db.add(doc)
        await db.commit()

        await service.approve_document(doc, admin_id, db)
        assert doc.status == "approved"
