"""Business logic for the Feishu ask flow.

handle_ask()         — first message: create Question, run Step 1 clarify/extract
resume_after_clarify() — subsequent message: continue clarification loop
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from sqlalchemy import select

from ..db.session import AsyncSessionLocal
from ..db.models import Question, User
from ..research_pipeline.steps import step1_clarify

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")


def _parse_tier(text: str) -> tuple[str, str]:
    """Extract --option <tier> from text. Returns (tier, cleaned_text)."""
    match = re.search(r"--option\s+(quick|normal|deep)", text, re.IGNORECASE)
    if match:
        tier = match.group(1).lower()
        cleaned = text[:match.start()].strip()
        return tier, cleaned
    return "normal", text.strip()


def _feishu_client() -> lark.Client:
    return (
        lark.Client.builder()
        .app_id(FEISHU_APP_ID)
        .app_secret(FEISHU_APP_SECRET)
        .build()
    )


async def _send_text(feishu_user_id: str, text: str) -> None:
    """Send a plain text message to a user."""
    try:
        client = _feishu_client()
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(feishu_user_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        await client.im.v1.message.acreate(req)
    except Exception as exc:
        print(f"[AskService] send_text failed: {exc}")


async def _get_or_create_user(feishu_user_id: str) -> User:
    """Find existing user or create a new one."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.feishu_user_id == feishu_user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            admin_ids = [
                uid.strip()
                for uid in os.environ.get("ADMIN_FEISHU_IDS", "").split(",")
                if uid.strip()
            ]
            user = User(
                feishu_user_id=feishu_user_id,
                name=feishu_user_id,
                role="admin" if feishu_user_id in admin_ids else "user",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user


async def handle_ask(feishu_user_id: str, raw_text: str, msg_id: str) -> None:
    """Handle a new question from Feishu: create Question, run Step 1."""
    tier, clean_text = _parse_tier(raw_text)
    user = await _get_or_create_user(feishu_user_id)

    async with AsyncSessionLocal() as db:
        question = Question(
            user_id=user.id,
            tier=tier,
            raw_text=clean_text,
            status="created",
        )
        db.add(question)
        await db.commit()
        await db.refresh(question)
        question_id = question.id

    await _send_text(feishu_user_id, "收到，正在分析您的问题...")

    # Run Step 1 clarify
    clarify_result = await step1_clarify.clarify(clean_text)

    if not clarify_result.get("is_valid", True):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Question).where(Question.id == question_id))
            q = result.scalar_one_or_none()
            if q:
                await db.delete(q)
                await db.commit()
        await _send_text(feishu_user_id, clarify_result.get("reply", "请输入半导体市场、产品、竞品或技术调研问题。"))
    elif not clarify_result["is_clear"]:
        questions_text = "\n".join(
            f"{i+1}. {q}"
            for i, q in enumerate(clarify_result["clarification_questions"])
        )
        clarify_msg = (
            "🤔 需要更多信息\n\n"
            "您的问题需要进一步明确：\n" + questions_text + "\n\n"
            "请直接回复补充信息，或回复「跳过」使用当前信息继续。"
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Question).where(Question.id == question_id))
            q = result.scalar_one_or_none()
            if q:
                q.status = "awaiting_clarify"
                q.clarified_text = clean_text
                await db.commit()

        await _send_text(feishu_user_id, clarify_msg)
    else:
        await _run_keywords(question_id, clean_text, "", feishu_user_id)


async def resume_after_clarify(question_id: int, user_reply: str) -> None:
    """Continue the clarification loop after user replies."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        question = result.scalar_one_or_none()
        if not question:
            return
        raw_text = question.raw_text or ""
        clarified_text = question.clarified_text or raw_text

    # Get feishu_user_id via join
    async with AsyncSessionLocal() as db:
        from ..db.models import User as UserModel
        result = await db.execute(
            select(UserModel.feishu_user_id)
            .join(Question, UserModel.id == Question.user_id)
            .where(Question.id == question_id)
        )
        row = result.first()
        feishu_user_id = row[0] if row else ""

    if not feishu_user_id:
        return

    # User replied "跳过" → skip clarification
    if user_reply.strip() in ("跳过", "skip", "Skip"):
        combined = clarified_text
    else:
        combined = f"{clarified_text}\n补充：{user_reply}"

    clarify_result = await step1_clarify.clarify(combined)

    if not clarify_result["is_clear"]:
        questions_text = "\n".join(
            f"{i+1}. {q}"
            for i, q in enumerate(clarify_result["clarification_questions"])
        )
        clarify_msg = (
            f"🤔 还需要更多信息：\n{questions_text}\n\n"
            f"请继续补充，或回复「跳过」继续。"
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Question).where(Question.id == question_id))
            q = result.scalar_one_or_none()
            if q:
                q.clarified_text = combined
                await db.commit()

        await _send_text(feishu_user_id, clarify_msg)
    else:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Question).where(Question.id == question_id))
            q = result.scalar_one_or_none()
            if q:
                q.clarified_text = combined
                await db.commit()

        await _run_keywords(question_id, combined, "", feishu_user_id)


async def _run_keywords(
    question_id: int, question_text: str, clarification_context: str, feishu_user_id: str
) -> None:
    """Extract keywords and send the confirmation card."""
    kw_result = await step1_clarify.extract_keywords(question_text, clarification_context)

    sub_questions = kw_result.get("sub_questions", [])
    keywords = kw_result.get("keywords", [])
    report_type = kw_result.get("report_type", "market")
    research_params = kw_result.get("params", {})

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Question).where(Question.id == question_id))
        q = result.scalar_one_or_none()
        if q:
            q.status = "awaiting_keyword"
            q.sub_questions_json = json.dumps(sub_questions, ensure_ascii=False)
            q.keywords_draft_json = json.dumps(keywords, ensure_ascii=False)
            q.report_type = report_type
            q.research_params_json = json.dumps(research_params, ensure_ascii=False)
            await db.commit()

    # Send keyword confirmation card
    from ..feishu_keyword_card.card_builder import build_keyword_card
    card_json = build_keyword_card(
        question_id=question_id,
        raw_text=question_text,
        sub_questions=sub_questions,
        keywords=keywords,
        report_type=report_type,
    )

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
        print(f"[AskService] send card failed: {exc}")
