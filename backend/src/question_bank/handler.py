from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.handler import get_current_user
from ..db.models import ChatMessage as StoredChatMessage
from ..db.models import ChatSession, TeachingPlan, User
from ..db.session import get_db
from ..integrations.llm_client import ChatMessage, LLMClient
from .service import (
    bank_stats,
    compact_question,
    get_question,
    is_contextual_follow_up,
    retrieve_context,
    search_questions,
)


router = APIRouter()

GUIDANCE_MODES = {
    "hint": "不要直接公布完整答案。先用一个关键问题或最小提示帮助学生迈出下一步，并等待学生回应。",
    "check": "重点检查学生提供的思路。先肯定正确部分，再精确指出第一个错误或缺口，只提示如何修正。",
    "step": "采用分步引导。每次聚焦一个推理阶段，解释本阶段目标并提出一个让学生继续作答的问题。",
    "full": "给出完整但清晰的解析：考点、分步推导、易错点、结论和一道可继续练习的建议。",
}


def _is_teacher(user: User) -> bool:
    return user.role == "teacher"


def _context_text(rows: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"【{row['ID']}｜{row.get('qtype')}｜{row.get('hard_level')}】\n"
        f"题目：{row.get('question')}\n选项：{row.get('choices')}\n"
        f"参考答案：{row.get('answer')}\n解析：{row.get('explanation')}\n"
        f"知识点：{'、'.join(row.get('keypoint') or [])}"
        for row in rows
    )


def _session_payload(session: ChatSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _message_payload(message: StoredChatMessage) -> dict[str, Any]:
    try:
        sources = json.loads(message.sources_json) if message.sources_json else []
    except json.JSONDecodeError:
        sources = []
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": sources,
        "model": message.model,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _tutor_system(user: User, guidance_mode: str) -> str:
    system = (
        "你是概率论与数理统计教学助手。必须以给定题库资料为核心作答，不得虚构题号、题干、答案或结论。"
        "先识别考点，使用 Markdown LaTeX 表示公式，引用题库内容时标明题号。资料不足时明确说明。"
        f"当前辅导方式：{GUIDANCE_MODES[guidance_mode]}"
    )
    if _is_teacher(user):
        system += "当前用户是教师，可以补充教学目标、课堂提问建议和分层讲解方法。"
    return system


def _sources_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_question(row, include_answer=False) for row in rows]


async def _owned_session(db: AsyncSession, session_id: int, user_id: int) -> ChatSession:
    session = (
        await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get("/question-bank/sessions")
async def list_chat_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
    ).scalars().all()
    return [_session_payload(item) for item in sessions]


@router.post("/question-bank/sessions")
async def create_chat_session(
    payload: dict = Body(default={}),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mode = str(payload.get("mode") or "answer")
    session = ChatSession(user_id=user.id, title="新对话", mode=mode)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_payload(session)


@router.get("/question-bank/sessions/{session_id}/messages")
async def list_chat_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, user.id)
    messages = (
        await db.execute(
            select(StoredChatMessage)
            .where(StoredChatMessage.session_id == session.id)
            .order_by(StoredChatMessage.id.asc())
        )
    ).scalars().all()
    return {"session": _session_payload(session), "messages": [_message_payload(item) for item in messages]}


@router.delete("/question-bank/sessions/{session_id}")
async def delete_chat_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(db, session_id, user.id)
    await db.execute(delete(StoredChatMessage).where(StoredChatMessage.session_id == session.id))
    await db.delete(session)
    await db.commit()
    return {"deleted": session_id}


@router.get("/question-bank/stats")
async def stats(_user: User = Depends(get_current_user)):
    return bank_stats()


@router.get("/question-bank/learning-summary")
async def learning_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
    ).scalars().all()
    session_ids = [item.id for item in sessions]
    messages = []
    if session_ids:
        messages = (
            await db.execute(
                select(StoredChatMessage)
                .where(
                    StoredChatMessage.session_id.in_(session_ids),
                    StoredChatMessage.role == "assistant",
                )
                .order_by(StoredChatMessage.id.desc())
                .limit(100)
            )
        ).scalars().all()
    question_ids: set[str] = set()
    keypoints: dict[str, int] = {}
    for item in messages:
        try:
            sources = json.loads(item.sources_json) if item.sources_json else []
        except (json.JSONDecodeError, TypeError):
            sources = []
        for source in sources:
            if source.get("ID"):
                question_ids.add(source["ID"])
            for keypoint in source.get("keypoint") or []:
                keypoints[keypoint] = keypoints.get(keypoint, 0) + 1
    return {
        "sessions": len(sessions),
        "questions_seen": len(question_ids),
        "assistant_answers": len(messages),
        "focus_keypoints": [
            {"name": name, "count": count}
            for name, count in sorted(keypoints.items(), key=lambda pair: (-pair[1], pair[0]))[:6]
        ],
        "recent_sessions": [_session_payload(item) for item in sessions[:5]],
    }


@router.get("/question-bank/questions")
async def list_questions(
    query: str = Query(""),
    qtype: str = Query(""),
    difficulty: str = Query(""),
    keypoint: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    rows, total = search_questions(
        query, qtype=qtype, difficulty=difficulty, keypoint=keypoint, page=page, page_size=page_size
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [compact_question(row, include_answer=_is_teacher(user)) for row in rows],
    }


@router.get("/question-bank/questions/{question_id}")
async def question_detail(question_id: str, user: User = Depends(get_current_user)):
    row = get_question(question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    # Students can reveal an answer from the detail drawer; hiding it in list views
    # prevents accidental spoilers while keeping self-study practical.
    return compact_question(row, include_answer=True) | {"teacher_view": _is_teacher(user)}


@router.post("/question-bank/assistant")
async def assistant(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入问题")
    mode = str(payload.get("mode") or "answer")
    guidance_mode = str(payload.get("guidance_mode") or "step")
    if guidance_mode not in GUIDANCE_MODES:
        raise HTTPException(status_code=400, detail="不支持的辅导方式")
    question_ids = [str(item) for item in payload.get("question_ids") or []]
    session_id = payload.get("session_id")
    if session_id:
        session = await _owned_session(db, int(session_id), user.id)
        session.mode = mode
    else:
        session = ChatSession(user_id=user.id, title=message[:36], mode=mode)
        db.add(session)
        await db.flush()

    history = (
        await db.execute(
            select(StoredChatMessage)
            .where(StoredChatMessage.session_id == session.id)
            .order_by(StoredChatMessage.id.desc())
            .limit(20)
        )
    ).scalars().all()
    history = list(reversed(history))
    prior_source_ids: list[str] = []
    for item in reversed(history):
        if item.sources_json:
            try:
                prior_source_ids.extend(source.get("ID", "") for source in json.loads(item.sources_json))
            except (json.JSONDecodeError, TypeError):
                pass
        if prior_source_ids:
            break
    carried_ids = prior_source_ids if is_contextual_follow_up(message) else []
    context_rows = retrieve_context(message, [*question_ids, *filter(None, carried_ids)], limit=6)
    session.updated_at = datetime.now(timezone.utc)
    if session.title == "新对话":
        session.title = message[:36]
    db.add(StoredChatMessage(session_id=session.id, role="user", content=message))
    await db.commit()
    await db.refresh(session)

    async def save_answer(answer_text: str, sources: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
        db.add(
            StoredChatMessage(
                session_id=session.id,
                role="assistant",
                content=answer_text,
                sources_json=json.dumps(sources, ensure_ascii=False),
                model=model_name,
            )
        )
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "answer": answer_text,
            "sources": sources,
            "model": model_name,
            "session_id": session.id,
        }

    if not context_rows:
        return await save_answer(
            "我暂时没有在当前题库中找到足够接近的题目。你可以换一个知识点、题号，或补充更完整的题干。",
            [],
            "retrieval-only",
        )

    if mode == "recommend":
        intro = "根据你的要求，我从题库中筛选了这些题。建议先独立作答，再查看解析："
        return await save_answer(
            intro,
            [compact_question(row, include_answer=False) for row in context_rows],
            "question-bank-retrieval",
        )

    system = _tutor_system(user, guidance_mode)
    try:
        conversation = [ChatMessage(item.role, item.content) for item in history]
        conversation.append(
            ChatMessage("user", f"题库资料：\n{_context_text(context_rows)}\n\n当前问题：{message}")
        )
        answer = await LLMClient(name="question_bank_tutor").chat(
            conversation,
            system=system,
            max_tokens=4096,
        )
        model = LLMClient().model
    except Exception:
        # Keep tutoring useful when the configured model endpoint, proxy, or API
        # key is temporarily unavailable.  The fallback is still grounded in the
        # retrieved question bank and never invents an answer.
        first = context_rows[0]
        answer = (
            f"大模型暂时不可用，先为你展示题库中的标准解析。\n\n"
            f"**{first['ID']}**\n\n{first.get('explanation') or first.get('answer')}"
        )
        model = "question-bank-fallback"
    return await save_answer(
        answer,
        _sources_from_rows(context_rows),
        model,
    )


@router.post("/question-bank/assistant/stream")
async def assistant_stream(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream newline-delimited JSON events while preserving the chat session."""
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入问题")
    mode = str(payload.get("mode") or "answer")
    guidance_mode = str(payload.get("guidance_mode") or "step")
    if guidance_mode not in GUIDANCE_MODES:
        raise HTTPException(status_code=400, detail="不支持的辅导方式")
    question_ids = [str(item) for item in payload.get("question_ids") or []]
    session_id = payload.get("session_id")
    if session_id:
        session = await _owned_session(db, int(session_id), user.id)
        session.mode = mode
    else:
        session = ChatSession(user_id=user.id, title=message[:36], mode=mode)
        db.add(session)
        await db.flush()

    history = (
        await db.execute(
            select(StoredChatMessage)
            .where(StoredChatMessage.session_id == session.id)
            .order_by(StoredChatMessage.id.desc())
            .limit(20)
        )
    ).scalars().all()
    history = list(reversed(history))
    prior_source_ids: list[str] = []
    for item in reversed(history):
        if item.sources_json:
            try:
                prior_source_ids.extend(source.get("ID", "") for source in json.loads(item.sources_json))
            except (json.JSONDecodeError, TypeError):
                pass
        if prior_source_ids:
            break
    carried_ids = prior_source_ids if is_contextual_follow_up(message) else []
    context_rows = retrieve_context(message, [*question_ids, *filter(None, carried_ids)], limit=6)
    sources = _sources_from_rows(context_rows)
    session.updated_at = datetime.now(timezone.utc)
    if session.title == "新对话":
        session.title = message[:36]
    db.add(StoredChatMessage(session_id=session.id, role="user", content=message))
    await db.commit()
    await db.refresh(session)

    async def events():
        def line(event: str, data: Any) -> str:
            return json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n"

        yield line("meta", {"session_id": session.id, "sources": sources})
        if not context_rows:
            answer = "我暂时没有在当前题库中找到足够接近的题目。请补充题号、知识点或更完整的题干。"
            yield line("delta", answer)
            model = "retrieval-only"
        elif mode == "recommend":
            answer = "我按知识点相关度筛选了这些题。建议先从较容易的题开始，并在独立作答后再查看解析。"
            yield line("delta", answer)
            model = "question-bank-retrieval"
        else:
            conversation = [ChatMessage(item.role, item.content) for item in history]
            conversation.append(ChatMessage("user", f"题库资料：\n{_context_text(context_rows)}\n\n当前问题：{message}"))
            client = LLMClient(name="question_bank_tutor")
            chunks: list[str] = []
            try:
                async for chunk in client.stream_chat(
                    conversation,
                    system=_tutor_system(user, guidance_mode),
                    max_tokens=4096,
                ):
                    chunks.append(chunk)
                    yield line("delta", chunk)
                answer = "".join(chunks)
                model = client.model
            except Exception:
                first = context_rows[0]
                fallback = (
                    "\n\n模型连接暂时中断，先展示题库中的标准解析：\n\n"
                    f"**{first['ID']}**\n\n{first.get('explanation') or first.get('answer')}"
                )
                chunks.append(fallback)
                yield line("delta", fallback)
                answer = "".join(chunks)
                model = "question-bank-fallback"
        db.add(
            StoredChatMessage(
                session_id=session.id,
                role="assistant",
                content=answer,
                sources_json=json.dumps(sources, ensure_ascii=False),
                model=model,
            )
        )
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        yield line("done", {"model": model})

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.get("/question-bank/teaching-plans")
async def list_teaching_plans(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_teacher(user):
        raise HTTPException(status_code=403, detail="仅教师可查看教学设计")
    plans = (
        await db.execute(
            select(TeachingPlan)
            .where(TeachingPlan.user_id == user.id)
            .order_by(TeachingPlan.updated_at.desc(), TeachingPlan.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": item.id,
            "title": item.title,
            "topic": item.topic,
            "duration": item.duration,
            "question_ids": json.loads(item.question_ids_json or "[]"),
            "content": item.content,
            "model": item.model,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in plans
    ]


@router.put("/question-bank/teaching-plans/{plan_id}")
async def update_teaching_plan(
    plan_id: int,
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = (
        await db.execute(
            select(TeachingPlan).where(TeachingPlan.id == plan_id, TeachingPlan.user_id == user.id)
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="教学设计不存在")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="教学设计内容不能为空")
    plan.content = content
    plan.title = str(payload.get("title") or plan.title).strip()[:160]
    plan.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": plan.id, "title": plan.title, "content": plan.content, "updated_at": plan.updated_at.isoformat()}


@router.delete("/question-bank/teaching-plans/{plan_id}")
async def delete_teaching_plan(
    plan_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = (
        await db.execute(
            select(TeachingPlan).where(TeachingPlan.id == plan_id, TeachingPlan.user_id == user.id)
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="教学设计不存在")
    await db.delete(plan)
    await db.commit()
    return {"deleted": plan_id}


@router.post("/question-bank/teaching-plan")
async def teaching_plan(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_teacher(user):
        raise HTTPException(status_code=403, detail="仅教师可生成教学设计")
    topic = str(payload.get("topic") or "").strip()
    question_ids = [str(item) for item in payload.get("question_ids") or []]
    objectives = str(payload.get("objectives") or "").strip()
    duration = int(payload.get("duration") or 45)
    rows = retrieve_context(topic or " ".join(question_ids), question_ids, limit=10)
    if not rows:
        raise HTTPException(status_code=400, detail="请填写教学主题或选择题目")
    system = (
        "你是大学概率论与数理统计课程的教学设计专家。仅依据提供的题库题目设计课堂，"
        "输出 Markdown，包含：教学目标、重难点、时间分配、导入、概念讲授、例题互动、分层练习、"
        "易错点诊断、课堂小结、课后任务。所有使用的题目必须标明题号，不得虚构题目。"
    )
    prompt = (
        f"主题：{topic or '根据所选题目归纳'}\n课时：{duration} 分钟\n教师补充目标：{objectives or '无'}\n\n"
        f"可用题目：\n{_context_text(rows)}"
    )
    try:
        content = await LLMClient(name="teaching_plan").chat(
            [ChatMessage("user", prompt)], system=system, max_tokens=6144
        )
        model = LLMClient().model
    except Exception:
        ids = "、".join(row["ID"] for row in rows)
        content = (
            f"# {topic or '概率论与数理统计'}教学设计\n\n"
            f"> 大模型暂时不可用，以下为基于题库的基础教学框架。\n\n"
            f"- 课时：{duration} 分钟\n- 例题：{ids}\n- 教学目标：{objectives or '理解核心概念并能完成典型题'}\n"
            "- 教学流程：概念回顾（10 分钟）→ 例题讲解（15 分钟）→ 分组练习（15 分钟）→ 总结（5 分钟）"
        )
        model = "question-bank-fallback"
    selected_ids = [row["ID"] for row in rows]
    plan = TeachingPlan(
        user_id=user.id,
        title=f"{topic or '概率统计'} · {duration} 分钟",
        topic=topic or "概率论与数理统计",
        duration=duration,
        objectives=objectives or None,
        question_ids_json=json.dumps(selected_ids, ensure_ascii=False),
        content=content,
        model=model,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {
        "id": plan.id,
        "title": plan.title,
        "content": content,
        "question_ids": selected_ids,
        "model": model,
    }
