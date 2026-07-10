"""Tests for the Feishu ask flow (feishu_bot_ask handler + service)."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy import select

from src.db.session import AsyncSessionLocal, engine, Base
from src.db.models import User, Question


@pytest.fixture(autouse=True)
async def db_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def test_user_id() -> str:
    return "ou_test_feishu_001"


async def test_handle_ask_creates_question(test_user_id: str) -> None:
    """handle_ask should create a Question record and run Step 1 clarify."""
    from src.feishu_bot_ask.handler import handle_message

    mock_clarify = AsyncMock(return_value={
        "is_clear": True, "reason": "clear", "clarification_questions": []
    })
    mock_extract = AsyncMock(return_value={
        "sub_questions": [{"id": "Q1", "text": "test question"}],
        "keywords": ["LDO", "PSRR"],
    })
    mock_send_text = AsyncMock()
    mock_send_card = AsyncMock()

    with (
        patch("src.research_pipeline.steps.step1_clarify.clarify", mock_clarify),
        patch("src.research_pipeline.steps.step1_clarify.extract_keywords", mock_extract),
        patch("src.feishu_bot_ask.service._send_text", mock_send_text),
        patch("src.feishu_bot_ask.service._feishu_client") as mock_client_factory,
    ):
        mock_client = MagicMock()
        mock_client.im.v1.message.acreate = AsyncMock()
        mock_client_factory.return_value = mock_client

        await handle_message(test_user_id, "LDO PSRR 怎么提高", "msg_001")

    # Question should have been created
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question)
            .join(User, Question.user_id == User.id)
            .where(User.feishu_user_id == test_user_id)
        )
        question = result.scalar_one_or_none()

    assert question is not None, "Question was not created"
    assert question.raw_text == "LDO PSRR 怎么提高"
    assert question.status == "awaiting_keyword"
    assert question.keywords_draft_json is not None


async def test_handle_ask_tier_parsing(test_user_id: str) -> None:
    """handle_ask should parse --option tier from message text."""
    from src.feishu_bot_ask.service import handle_ask

    mock_clarify = AsyncMock(return_value={
        "is_clear": True, "reason": "clear", "clarification_questions": []
    })
    mock_extract = AsyncMock(return_value={
        "sub_questions": [], "keywords": ["ADC"],
    })
    mock_send_text = AsyncMock()

    with (
        patch("src.research_pipeline.steps.step1_clarify.clarify", mock_clarify),
        patch("src.research_pipeline.steps.step1_clarify.extract_keywords", mock_extract),
        patch("src.feishu_bot_ask.service._send_text", mock_send_text),
        patch("src.feishu_bot_ask.service._feishu_client") as mock_client_factory,
    ):
        mock_client = MagicMock()
        mock_client.im.v1.message.acreate = AsyncMock()
        mock_client_factory.return_value = mock_client

        await handle_ask(test_user_id, "ADC SNR 怎么提高 --option deep", "msg_002")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question)
            .join(User, Question.user_id == User.id)
            .where(User.feishu_user_id == test_user_id)
        )
        question = result.scalar_one_or_none()

    assert question is not None
    assert question.tier == "deep"
    assert "--option" not in question.raw_text


async def test_handle_ask_awaiting_clarify_state(test_user_id: str) -> None:
    """When LLM says not clear, Question should be set to awaiting_clarify."""
    from src.feishu_bot_ask.service import handle_ask

    mock_clarify = AsyncMock(return_value={
        "is_clear": False,
        "reason": "too vague",
        "clarification_questions": ["目标 PSRR 是多少？", "工艺节点？"],
    })
    mock_send_text = AsyncMock()

    with (
        patch("src.research_pipeline.steps.step1_clarify.clarify", mock_clarify),
        patch("src.feishu_bot_ask.service._send_text", mock_send_text),
    ):
        await handle_ask(test_user_id, "模拟电路怎么设计", "msg_003")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question)
            .join(User, Question.user_id == User.id)
            .where(User.feishu_user_id == test_user_id)
        )
        question = result.scalar_one_or_none()

    assert question is not None
    assert question.status == "awaiting_clarify"
    mock_send_text.assert_called()  # clarification message was sent


async def test_resume_after_clarify_routes_correctly(test_user_id: str) -> None:
    """resume_after_clarify should re-run clarify and eventually extract keywords."""
    from src.feishu_bot_ask.handler import handle_message

    # Seed: user with an awaiting_clarify question
    async with AsyncSessionLocal() as db:
        user = User(feishu_user_id=test_user_id, name="Test", role="user")
        db.add(user)
        await db.flush()

        question = Question(
            user_id=user.id,
            tier="normal",
            raw_text="模拟电路",
            clarified_text="模拟电路",
            status="awaiting_clarify",
        )
        db.add(question)
        await db.commit()
        question_id = question.id

    mock_clarify = AsyncMock(return_value={
        "is_clear": True, "reason": "now clear", "clarification_questions": []
    })
    mock_extract = AsyncMock(return_value={
        "sub_questions": [{"id": "Q1", "text": "LDO PSRR"}],
        "keywords": ["LDO", "PSRR"],
    })
    mock_send_text = AsyncMock()

    with (
        patch("src.research_pipeline.steps.step1_clarify.clarify", mock_clarify),
        patch("src.research_pipeline.steps.step1_clarify.extract_keywords", mock_extract),
        patch("src.feishu_bot_ask.service._send_text", mock_send_text),
        patch("src.feishu_bot_ask.service._feishu_client") as mock_client_factory,
    ):
        mock_client = MagicMock()
        mock_client.im.v1.message.acreate = AsyncMock()
        mock_client_factory.return_value = mock_client

        # User replies to the awaiting_clarify question
        await handle_message(test_user_id, "LDO，目标 60dB PSRR", "msg_004")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        question = result.scalar_one_or_none()

    assert question.status == "awaiting_keyword"
