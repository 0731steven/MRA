"""Quick test for document review (approve / reject) against the pipeline temp DB.

Usage:  python _test_review.py
"""
import asyncio
import glob
import os
import sys
from pathlib import Path

# Point to the latest pipeline temp DB
tmp_dirs = sorted(glob.glob(os.path.expanduser(r"~\AppData\Local\Temp\full_real_run_*")),
                  key=os.path.getmtime, reverse=True)
if not tmp_dirs:
    print("No pipeline temp DB found"); sys.exit(1)
db_path = Path(tmp_dirs[0]) / "real.db"
print(f"[setup] DB: {db_path}")

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
os.environ["WILSON_LIB_PATH"] = "D:/wilson_lib"
os.environ["APP_ENV"] = "development"

sys.path.insert(0, str(Path(__file__).parent))

from src.db.session import engine, Base, AsyncSessionLocal
from src.db.models import PendingDocument, User
from src.document_review import service
from sqlalchemy import select


async def main():
    # List all pending docs
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingDocument).where(PendingDocument.status == "pending")
        )
        pending = result.scalars().all()
        print(f"\n{'='*60}")
        print(f"Pending documents: {len(pending)}")
        print(f"{'='*60}")
        for d in pending:
            src = Path(d.staging_path)
            dst = Path(os.environ["WILSON_LIB_PATH"]) / d.target_path
            exists = "EXISTS" if src.exists() else "MISSING"
            print(f"  [{d.id:2d}] {d.source:7s} | {d.title[:55]}")
            print(f"       staging: {src}  [{exists}]")
            print(f"       target:  {dst}")

    if not pending:
        print("Nothing to review."); return

    # --- Test 1: Approve first IEEE paper (id=1) ---
    print(f"\n{'='*60}")
    print("TEST 1: Approve doc id=1 (first IEEE paper)")
    print(f"{'='*60}")
    async with AsyncSessionLocal() as db:
        # Ensure we have an admin user
        result = await db.execute(select(User).where(User.role == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            admin = User(feishu_user_id="test-admin", name="Test Admin", role="admin")
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
            print(f"  Created admin user: id={admin.id}")

        result = await db.execute(select(PendingDocument).where(PendingDocument.id == 1))
        doc = result.scalar_one_or_none()
        if doc and doc.status == "pending":
            src = Path(doc.staging_path)
            dst = Path(os.environ["WILSON_LIB_PATH"]) / doc.target_path
            print(f"  Before: staging exists={src.exists()}, target exists={dst.exists()}")
            await service.approve_document(doc, admin.id, db)
            print(f"  After:  staging exists={src.exists()}, target exists={dst.exists()}")
            print(f"  Status: {doc.status}, reviewed_by: {doc.reviewed_by}")
            if dst.exists():
                if dst.is_dir():
                    files = list(dst.rglob("*"))
                    print(f"  Target dir has {len(files)} files")
                    for f in files[:5]:
                        print(f"    {f.relative_to(dst)}")
                else:
                    print(f"  Target file size: {dst.stat().st_size} bytes")
            print("  [PASS] APPROVE TEST" if dst.exists() else "  [FAIL] APPROVE TEST")
        else:
            print(f"  Skipped (doc status={doc.status if doc else 'not found'})")

    # --- Test 2: Reject last patent (id=16) ---
    print(f"\n{'='*60}")
    print("TEST 2: Reject doc id=16 (last patent)")
    print(f"{'='*60}")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PendingDocument).where(PendingDocument.id == 16))
        doc = result.scalar_one_or_none()
        if doc and doc.status == "pending":
            src = Path(doc.staging_path)
            print(f"  Before: staging exists={src.exists()}")
            await service.reject_document(doc, admin.id, db)
            print(f"  After:  staging exists={src.exists()}")
            print(f"  Status: {doc.status}, reviewed_by: {doc.reviewed_by}")
            print("  [PASS] REJECT TEST" if not src.exists() else "  [FAIL] REJECT TEST")
        else:
            print(f"  Skipped (doc status={doc.status if doc else 'not found'})")

    # --- Test 3: Batch approve remaining IEEE papers (ids 2-10) ---
    print(f"\n{'='*60}")
    print("TEST 3: Batch approve remaining IEEE papers (ids 2-10)")
    print(f"{'='*60}")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingDocument).where(
                PendingDocument.status == "pending",
                PendingDocument.source == "ieee",
            )
        )
        remaining_ieee = result.scalars().all()
        print(f"  Remaining IEEE pending: {len(remaining_ieee)}")
        moved = 0
        for doc in remaining_ieee:
            src = Path(doc.staging_path)
            dst = Path(os.environ["WILSON_LIB_PATH"]) / doc.target_path
            await service.approve_document(doc, admin.id, db)
            if dst.exists():
                moved += 1
        print(f"  Moved {moved}/{len(remaining_ieee)} to vault")
        print(f"  {'[PASS]' if moved == len(remaining_ieee) else '[FAIL]'} BATCH APPROVE TEST")

    # --- Final status summary ---
    print(f"\n{'='*60}")
    print("FINAL STATUS")
    print(f"{'='*60}")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PendingDocument))
        all_docs = result.scalars().all()
        by_status = {}
        for d in all_docs:
            by_status.setdefault(d.status, []).append(d)
        for st, docs in sorted(by_status.items()):
            print(f"  {st}: {len(docs)} docs")
            for d in docs:
                print(f"    [{d.id:2d}] {d.source:7s} | {d.title[:50]}")

    # Verify vault structure
    print(f"\n{'='*60}")
    print("VAULT STRUCTURE AFTER APPROVAL")
    print(f"{'='*60}")
    vault = Path(os.environ["WILSON_LIB_PATH"])
    for sub in ["ieee_paper_md", "patent_md"]:
        p = vault / sub
        if p.exists():
            dirs = [d for d in p.rglob("*") if d.is_dir() and not any(d.iterdir() and d2.is_dir() for d2 in d.iterdir())]
            md_files = list(p.rglob("*.md"))
            png_files = list(p.rglob("*.png"))
            print(f"  {sub}/: {len(md_files)} md, {len(png_files)} png")
        else:
            print(f"  {sub}/: does not exist")


if __name__ == "__main__":
    asyncio.run(main())
