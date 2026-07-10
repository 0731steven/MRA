"""Tests for feishu_keyword_card card handler."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy import select

from src.db.session import AsyncSessionLocal, engine, Base
from src.db.models import User, Question, ResearchTask


@pytest.fixture(autouse=True)
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def seeded_question_id() -> int:
    """Seed a Question in awaiting_keyword state."""
    async with AsyncSessionLocal() as db:
        user = User(feishu_user_id="ou_card_test", name="Card Test", role="user")
        db.add(user)
        await db.flush()

        question = Question(
            user_id=user.id,
            tier="normal",
            raw_text="LDO PSRR 怎么提高",
            clarified_text="LDO PSRR 怎么提高",
            sub_questions_json=json.dumps([{"id": "Q1", "text": "LDO PSRR 限制因素"}]),
            keywords_draft_json=json.dumps(["LDO", "PSRR"]),
            status="awaiting_keyword",
        )
        db.add(question)
        await db.commit()
        await db.refresh(question)
        return question.id


async def test_confirm_starts_pipeline(seeded_question_id: int) -> None:
    """Confirm action should call start_pipeline and set Question.status=running."""
    from src.feishu_keyword_card.card_handler import handle_card_action

    mock_start = AsyncMock(return_value=MagicMock(id=99))

    action_value = {
        "action": "confirm",
        "question_id": str(seeded_question_id),
        "tier": "deep",
    }

    with patch("src.research_pipeline.scheduler.start_pipeline", mock_start):
        await handle_card_action("ou_card_test", action_value)

    mock_start.assert_awaited_once_with(seeded_question_id, ["LDO", "PSRR"])

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == seeded_question_id))
        question = result.scalar_one_or_none()

    assert question.status == "running"
    assert question.tier == "deep"


async def test_cancel_marks_question_cancelled(seeded_question_id: int) -> None:
    """Cancel action should set Question.status=cancelled."""
    from src.feishu_keyword_card.card_handler import handle_card_action

    action_value = {
        "action": "cancel",
        "question_id": str(seeded_question_id),
    }

    await handle_card_action("ou_card_test", action_value)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == seeded_question_id))
        question = result.scalar_one_or_none()

    assert question.status == "cancelled"


async def test_card_builder_structure(seeded_question_id: int) -> None:
    """build_keyword_card should return valid card JSON with required elements."""
    from src.feishu_keyword_card.card_builder import build_keyword_card

    card = build_keyword_card(
        question_id=seeded_question_id,
        raw_text="LDO PSRR 怎么提高",
        sub_questions=[{"id": "Q1", "text": "限制因素"}],
        keywords=["LDO", "PSRR"],
    )

    assert card["header"]["title"]["content"] == "🔍 关键词确认"
    elements = card["elements"]
    # Find the action element
    action_elements = [e for e in elements if e.get("tag") == "action"]
    assert action_elements, "No action element in card"

    actions = action_elements[0]["actions"]
    action_names = [a["value"]["action"] for a in actions]
    assert "confirm" in action_names
    assert "revise" in action_names
    assert "cancel" in action_names
