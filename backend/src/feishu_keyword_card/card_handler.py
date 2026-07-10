"""Handles Feishu card button callbacks for the keyword confirmation card."""
from __future__ import annotations

import json

from sqlalchemy import select

from ..db.session import AsyncSessionLocal
from ..db.models import Question, User


async def handle_card_action(feishu_user_id: str, action_value: dict) -> None:
    """Dispatch card button actions: confirm / revise / cancel / set_tier."""
    action = action_value.get("action", "")
    try:
        question_id = int(action_value.get("question_id", 0))
    except (ValueError, TypeError):
        return

    if not question_id:
        return

    if action == "confirm":
        await _confirm(feishu_user_id, question_id, action_value)
    elif action == "revise":
        await _revise(feishu_user_id, question_id, action_value)
    elif action == "cancel":
        await _cancel(question_id)
    # set_tier is handled client-side in the card; no server action needed


async def _confirm(feishu_user_id: str, question_id: int, action_value: dict) -> None:
    """User confirmed keywords: start the pipeline."""
    tier = action_value.get("tier", "normal")
    if tier not in ("quick", "normal", "deep"):
        tier = "normal"

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        question = result.scalar_one_or_none()
        if not question or question.status != "awaiting_keyword":
            return

        keywords: list[str] = []
        if question.keywords_draft_json:
            try:
                keywords = json.loads(question.keywords_draft_json)
            except Exception:
                pass

        question.tier = tier
        question.status = "running"
        await db.commit()

    if not keywords:
        return

    from ..research_pipeline.scheduler import start_pipeline
    await start_pipeline(question_id, keywords)


async def _revise(feishu_user_id: str, question_id: int, action_value: dict) -> None:
    """User wants to revise keywords: re-extract with updated input."""
    new_keywords_raw = action_value.get("keywords", "")
    if not new_keywords_raw:
        # No new keywords provided; just resend the existing card
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Question).where(Question.id == question_id))
            question = result.scalar_one_or_none()
            if not question:
                return
            sub_questions = json.loads(question.sub_questions_json or "[]")
            keywords = json.loads(question.keywords_draft_json or "[]")
            raw_text = question.clarified_text or question.raw_text or ""
            report_type = question.report_type or "market"

        from .card_builder import build_keyword_card
        from ..feishu_bot_ask.service import _feishu_client
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        card_json = build_keyword_card(question_id, raw_text, sub_questions, keywords, report_type=report_type)
        try:
            client = _feishu_client()
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(feishu_user_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_json))
                    .build()
                )
                .build()
            )
            await client.im.v1.message.acreate(req)
        except Exception as exc:
            print(f"[CardHandler] revise resend failed: {exc}")
        return

    # Update keywords_draft_json with user-provided keywords
    if isinstance(new_keywords_raw, str):
        new_keywords = [kw.strip() for kw in new_keywords_raw.split(",") if kw.strip()]
    elif isinstance(new_keywords_raw, list):
        new_keywords = new_keywords_raw
    else:
        new_keywords = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        question = result.scalar_one_or_none()
        if not question:
            return
        question.keywords_draft_json = json.dumps(new_keywords, ensure_ascii=False)
        sub_questions = json.loads(question.sub_questions_json or "[]")
        raw_text = question.clarified_text or question.raw_text or ""
        report_type = question.report_type or "market"
        await db.commit()

    # Resend updated card
    from .card_builder import build_keyword_card
    from ..feishu_bot_ask.service import _feishu_client
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    card_json = build_keyword_card(question_id, raw_text, sub_questions, new_keywords, report_type=report_type)
    try:
        client = _feishu_client()
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(feishu_user_id)
                .msg_type("interactive")
                .content(json.dumps(card_json))
                .build()
            )
            .build()
        )
        await client.im.v1.message.acreate(req)
    except Exception as exc:
        print(f"[CardHandler] revise send failed: {exc}")


async def _cancel(question_id: int) -> None:
    """User cancelled: mark Question as cancelled."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        question = result.scalar_one_or_none()
        if question:
            question.status = "cancelled"
            await db.commit()
