"""Feishu message handler for the ask flow.

Routes incoming messages to either:
- handle_ask()           — new question
- resume_after_clarify() — reply to a pending clarification
"""
from __future__ import annotations

from sqlalchemy import select

from ..db.session import AsyncSessionLocal
from ..db.models import Question, User
from .service import handle_ask, resume_after_clarify


async def _find_awaiting_clarify(feishu_user_id: str) -> Question | None:
    """Find the most recent Question awaiting clarification for this user."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question)
            .join(User, Question.user_id == User.id)
            .where(
                User.feishu_user_id == feishu_user_id,
                Question.status == "awaiting_clarify",
            )
            .order_by(Question.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def handle_message(feishu_user_id: str, text: str, msg_id: str) -> None:
    """Route an incoming Feishu text message."""
    question = await _find_awaiting_clarify(feishu_user_id)
    if question:
        await resume_after_clarify(question.id, text)
    else:
        await handle_ask(feishu_user_id, text, msg_id)
