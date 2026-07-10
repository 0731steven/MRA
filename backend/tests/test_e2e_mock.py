"""End-to-end mock pipeline test.

Runs the full orchestrator (Steps 3–10b) with:
  - DEEPSEEK_MOCK=true  (returns JSON-safe placeholder strings)
  - All cad_tools subprocess calls replaced with AsyncMock
  - SQLite temp database (set by conftest.pytest_configure)

Asserts that task.status transitions to "done" and report_path is set in context.
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from src.db.session import AsyncSessionLocal, engine, Base
from src.db.models import User, Question, ResearchTask, Report
from src.research_pipeline import orchestrator


# ── DB setup ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def db_tables():
    """Create all tables before test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def seeded_task_id() -> int:
    """Insert User → Question → ResearchTask; return task.id."""
    async with AsyncSessionLocal() as db:
        user = User(
            feishu_user_id="ou_test_user_001",
            name="Test User",
            role="user",
        )
        db.add(user)
        await db.flush()

        question = Question(
            user_id=user.id,
            tier="quick",
            raw_text="ADC SNR improvement techniques",
            clarified_text="How to improve ADC signal-to-noise ratio in 28nm CMOS?",
            sub_questions_json=json.dumps([
                {"id": "Q1", "text": "What are the main factors limiting ADC SNR?", "coverage": "❌"},
                {"id": "Q2", "text": "Which circuit techniques improve ADC SNR?", "coverage": "❌"},
            ]),
            status="running",
        )
        db.add(question)
        await db.flush()

        task = ResearchTask(
            question_id=question.id,
            status="step3_local_search",
            current_step="step3_local_search",
            keywords_json=json.dumps(["ADC", "SNR", "CMOS"]),
            started_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


# ── Mock return values ─────────────────────────────────────────────────────────

def _make_mocks() -> dict:
    return {
        "src.integrations.cad_tools.local_search":
            AsyncMock(return_value={"results": []}),
        "src.integrations.cad_tools.ieee_search_candidates":
            AsyncMock(return_value={"papers": [], "results": []}),
        "src.integrations.cad_tools.ieee_download":
            AsyncMock(return_value={"new_papers": [], "papers": []}),
        "src.integrations.cad_tools.ingest_pdf":
            AsyncMock(return_value={}),
        "src.integrations.cad_tools.patent_search_candidates":
            AsyncMock(return_value={"patents": [], "results": []}),
        "src.integrations.cad_tools.patent_download":
            AsyncMock(return_value={}),
        "src.integrations.cad_tools.patent_convert":
            AsyncMock(return_value={}),
        "src.integrations.cad_tools.web_search":
            AsyncMock(return_value={"results": []}),
        "src.integrations.cad_tools.web_ingest":
            AsyncMock(return_value={}),
        # Gate must return exit_code=0 so the pipeline doesn't loop/degrade
        "src.integrations.cad_tools.check_report":
            AsyncMock(return_value=(0, "All checks passed")),
        "src.integrations.cad_tools.fix_citations":
            AsyncMock(return_value={}),
        "src.integrations.cad_tools.export_report":
            AsyncMock(return_value={"zip_path": ""}),
    }


# ── Test ──────────────────────────────────────────────────────────────────────

async def test_pipeline_mock_runs_to_done(seeded_task_id: int) -> None:
    """Full orchestrator run with mocked I/O should reach status='done'."""
    mocks = _make_mocks()

    with patch.multiple("src.integrations.cad_tools", **{
        k.split(".")[-1]: v for k, v in mocks.items()
    }):
        await orchestrator.run(seeded_task_id, ["ADC", "SNR", "CMOS"])

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchTask).where(ResearchTask.id == seeded_task_id)
        )
        task = result.scalar_one_or_none()

    assert task is not None, "ResearchTask disappeared from DB"
    assert task.status == "done", (
        f"Expected status='done', got '{task.status}'.\n"
        f"error_trace:\n{task.error_trace}"
    )

    ctx_data: dict = json.loads(task.context_json) if task.context_json else {}
    assert ctx_data.get("report_path"), (
        "context_json.report_path is empty — step9 did not write the report"
    )


async def test_pipeline_mock_local_shortcut(seeded_task_id: int) -> None:
    """If local search returns an existing report, pipeline takes the shortcut path."""
    def _local_with_report(*_args, **_kwargs):
        return {"results": [
            {"path": "wiki/research/old_adc_report.md", "type": "report", "title": "Old ADC Report"}
        ]}

    mocks = _make_mocks()
    mocks["src.integrations.cad_tools.local_search"] = AsyncMock(
        side_effect=_local_with_report
    )

    with patch.multiple("src.integrations.cad_tools", **{
        k.split(".")[-1]: v for k, v in mocks.items()
    }):
        await orchestrator.run(seeded_task_id, ["ADC", "SNR", "CMOS"])

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchTask).where(ResearchTask.id == seeded_task_id)
        )
        task = result.scalar_one_or_none()

    # Shortcut path also ends in "done"
    assert task.status == "done", (
        f"Expected 'done', got '{task.status}'.\nerror_trace: {task.error_trace}"
    )

    # ieee_download should NOT have been called (shortcut skips remote search)
    mocks["src.integrations.cad_tools.ieee_download"].assert_not_called()


async def test_report_db_record_created(seeded_task_id: int) -> None:
    """step9 should insert a Report row after writing the report file."""
    mocks = _make_mocks()

    with patch.multiple("src.integrations.cad_tools", **{
        k.split(".")[-1]: v for k, v in mocks.items()
    }):
        await orchestrator.run(seeded_task_id, ["ADC", "SNR", "CMOS"])

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Report).where(Report.task_id == seeded_task_id)
        )
        report = result.scalar_one_or_none()

    assert report is not None, "Report row was not created in DB"
    assert report.vault_path, "Report.vault_path is empty"
    assert report.summary_text, "Report.summary_text is empty"


async def test_question_status_synced(seeded_task_id: int) -> None:
    """orchestrator should set Question.status='done' when task completes."""
    mocks = _make_mocks()

    # Get the question_id from the task
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResearchTask).where(ResearchTask.id == seeded_task_id)
        )
        task = result.scalar_one_or_none()
        question_id = task.question_id

    with patch.multiple("src.integrations.cad_tools", **{
        k.split(".")[-1]: v for k, v in mocks.items()
    }):
        await orchestrator.run(seeded_task_id, ["ADC", "SNR", "CMOS"])

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question).where(Question.id == question_id)
        )
        question = result.scalar_one_or_none()

    assert question is not None
    assert question.status == "done", (
        f"Expected Question.status='done', got '{question.status}'"
    )
