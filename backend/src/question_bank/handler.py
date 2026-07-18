from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.handler import get_current_user
from ..db.models import ChatMessage as StoredChatMessage
from ..db.models import (
    AssignmentItem,
    AssignmentRecipient,
    ChatSession,
    Classroom,
    ExperimentRecord,
    LearningAssignment,
    QuestionAttempt,
    TeachingPlan,
    User,
)
from ..db.session import get_db
from ..integrations.llm_client import ChatMessage, LLMClient
from .analytics import (
    build_learning_profile,
    build_teaching_insights,
    experiment_catalog,
    select_layered_questions,
)
from .service import (
    bank_stats,
    compact_question,
    get_question,
    is_contextual_follow_up,
    load_questions,
    retrieve_context,
    search_questions,
)
from .teaching_package import LEARNER_PROFILES, LESSON_TYPES, build_teaching_package


router = APIRouter()

GUIDANCE_MODES = {
    "hint": "不要直接公布完整答案。先用一个关键问题或最小提示帮助学生迈出下一步，并等待学生回应。",
    "check": "重点检查学生提供的思路。先肯定正确部分，再精确指出第一个错误或缺口，只提示如何修正。",
    "step": "采用分步引导。每次聚焦一个推理阶段，解释本阶段目标并提出一个让学生继续作答的问题。",
    "full": "给出完整但清晰的解析：考点、分步推导、易错点、结论和一道可继续练习的建议。",
}

MATH_MARKDOWN_RULE = (
    "所有数学公式必须使用 Markdown 数学分隔符：行内公式用 $...$，独立公式用 $$...$$；"
    "不要使用 \\(...\\) 或 \\[...\\]。"
)


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
        f"先识别考点，使用 Markdown LaTeX 表示公式。{MATH_MARKDOWN_RULE}"
        "引用题库内容时标明题号。资料不足时明确说明。"
        f"当前辅导方式：{GUIDANCE_MODES[guidance_mode]}"
    )
    if _is_teacher(user):
        system += "当前用户是教师，可以补充教学目标、课堂提问建议和分层讲解方法。"
    return system


def _sources_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_question(row, include_answer=False) for row in rows]


def _attempt_analytics_payload(attempt: QuestionAttempt) -> dict[str, Any]:
    return {
        "question_id": attempt.question_id,
        "verdict": attempt.verdict,
        "error_type": attempt.error_type,
        "hint_count": attempt.hint_count,
        "attempt_no": attempt.attempt_no,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
    }


def _layer_payload(question_ids: list[str]) -> dict[str, list[str]]:
    layers = {"易": [], "中": [], "难": []}
    for question_id in question_ids:
        row = get_question(question_id)
        if row and row.get("hard_level") in layers:
            layers[str(row["hard_level"])].append(question_id)
    return layers


def _stored_plan_payload(plan: TeachingPlan) -> dict[str, Any]:
    question_ids = json.loads(plan.question_ids_json or "[]")
    rows = [row for question_id in question_ids if (row := get_question(question_id))]
    generated = build_teaching_package(
        topic=plan.topic,
        duration=plan.duration,
        objectives=plan.objectives or "",
        rows=rows,
        insights=build_teaching_insights(rows, []),
        lesson_type=plan.lesson_type or "concept",
        learner_profile=plan.learner_profile or "mixed",
    ) if rows else {"manifest": {}, "student_content": ""}
    try:
        package = json.loads(plan.package_json) if plan.package_json else generated["manifest"]
    except (json.JSONDecodeError, TypeError):
        package = generated["manifest"]
    return {
        "id": plan.id,
        "title": plan.title,
        "topic": plan.topic,
        "duration": plan.duration,
        "classroom_id": plan.classroom_id,
        "lesson_type": plan.lesson_type or "concept",
        "learner_profile": plan.learner_profile or "mixed",
        "question_ids": question_ids,
        "layers": _layer_payload(question_ids),
        "content": plan.content,
        "student_content": plan.student_content or generated["student_content"],
        "package": package,
        "model": plan.model,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


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
    attempts = (
        await db.execute(
            select(QuestionAttempt)
            .where(QuestionAttempt.user_id == user.id)
            .order_by(QuestionAttempt.id.desc())
            .limit(200)
        )
    ).scalars().all()
    attempted_ids = {item.question_id for item in attempts}
    correct_ids = {item.question_id for item in attempts if item.verdict == "correct"}
    error_types: dict[str, int] = {}
    for item in attempts:
        if item.error_type:
            error_types[item.error_type] = error_types.get(item.error_type, 0) + 1
    experiment_runs = (
        await db.execute(
            select(func.count(ExperimentRecord.id)).where(ExperimentRecord.user_id == user.id)
        )
    ).scalar_one()
    return {
        "sessions": len(sessions),
        "questions_seen": len(question_ids),
        "assistant_answers": len(messages),
        "attempts": len(attempts),
        "attempted_questions": len(attempted_ids),
        "correct_questions": len(correct_ids),
        "experiment_runs": experiment_runs,
        "error_types": [
            {"name": name, "count": count}
            for name, count in sorted(error_types.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        ],
        "focus_keypoints": [
            {"name": name, "count": count}
            for name, count in sorted(keypoints.items(), key=lambda pair: (-pair[1], pair[0]))[:6]
        ],
        "recent_sessions": [_session_payload(item) for item in sessions[:5]],
    }


@router.get("/question-bank/learning-profile")
async def learning_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempts = (
        await db.execute(
            select(QuestionAttempt)
            .where(QuestionAttempt.user_id == user.id)
            .order_by(QuestionAttempt.id.desc())
            .limit(500)
        )
    ).scalars().all()
    return build_learning_profile(
        load_questions(),
        [_attempt_analytics_payload(item) for item in attempts],
    )


@router.get("/question-bank/teaching-insights")
async def teaching_insights(
    topic: str = Query(""),
    question_ids: str = Query(""),
    classroom_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_teacher(user):
        raise HTTPException(status_code=403, detail="仅教师可查看认知断层预警")
    explicit_ids = [item.strip().upper() for item in question_ids.split(",") if item.strip()]
    retrieved = retrieve_context(topic or " ".join(explicit_ids), explicit_ids, limit=30)
    rows = select_layered_questions(retrieved, limit=12)
    if not rows:
        raise HTTPException(status_code=400, detail="请提供教学主题或题号")
    attempt_query = (
        select(QuestionAttempt)
        .join(LearningAssignment, LearningAssignment.id == QuestionAttempt.assignment_id)
        .join(Classroom, Classroom.id == LearningAssignment.classroom_id)
        .where(Classroom.teacher_id == user.id)
        .order_by(QuestionAttempt.id.desc())
        .limit(2000)
    )
    if classroom_id is not None:
        classroom = (
            await db.execute(
                select(Classroom).where(Classroom.id == classroom_id, Classroom.teacher_id == user.id)
            )
        ).scalar_one_or_none()
        if classroom is None:
            raise HTTPException(status_code=404, detail="班级不存在或不属于当前教师")
        attempt_query = attempt_query.where(Classroom.id == classroom_id)
    attempts = (await db.execute(attempt_query)).scalars().all()
    return {
        "topic": topic or "根据所选题目归纳",
        "question_ids": [row["ID"] for row in rows],
        **build_teaching_insights(rows, [_attempt_analytics_payload(item) for item in attempts]),
    }


@router.get("/question-bank/experiments/catalog")
async def experiments_catalog(_user: User = Depends(get_current_user)):
    return experiment_catalog(load_questions())


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


@router.post("/question-bank/questions/{question_id}/hint")
async def question_hint(
    question_id: str,
    payload: dict = Body(default={}),
    _user: User = Depends(get_current_user),
):
    row = get_question(question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    answer = str(payload.get("answer") or "").strip()
    reasoning = str(payload.get("reasoning") or "").strip()
    prompt = (
        f"题目：{row.get('question')}\n知识点：{'、'.join(row.get('keypoint') or [])}\n"
        f"标准答案：{row.get('answer')}\n标准解析：{row.get('explanation')}\n"
        f"学生当前答案：{answer or '未填写'}\n学生思路：{reasoning or '未填写'}\n"
        "只给一个能推动下一步的提示，不得直接公布答案，控制在80字以内。"
    )
    try:
        hint = await LLMClient(name="answer_hint").chat(
            [ChatMessage("user", prompt)],
            system=f"你是启发式概率统计教师，只提供最小必要提示。{MATH_MARKDOWN_RULE}",
            max_tokens=256,
        )
    except Exception:
        keypoint = "、".join(row.get("keypoint") or [])
        hint = f"先明确这道题涉及的事件和已知条件，再判断应使用哪个公式。重点回顾：{keypoint}。"
    return {"hint": hint}


@router.post("/question-bank/questions/{question_id}/attempts")
async def submit_question_attempt(
    question_id: str,
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = get_question(question_id)
    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    answer = str(payload.get("answer") or "").strip()
    reasoning = str(payload.get("reasoning") or "").strip()
    image_name = str(payload.get("image_name") or "").strip()[:255]
    image_data_url = str(payload.get("image_data_url") or "")
    if image_data_url and (not image_data_url.startswith("data:image/") or len(image_data_url) > 3_000_000):
        raise HTTPException(status_code=400, detail="手写图片格式无效或超过约 2MB")
    if not answer and not reasoning and not image_name:
        raise HTTPException(status_code=400, detail="请填写答案、描述思路或上传手写过程")
    assignment_id = None
    recipient = None
    if payload.get("assignment_id") is not None:
        try:
            assignment_id = int(payload["assignment_id"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="任务编号无效") from exc
        assignment = (
            await db.execute(
                select(LearningAssignment).where(
                    LearningAssignment.id == assignment_id,
                    LearningAssignment.status == "published",
                )
            )
        ).scalar_one_or_none()
        recipient = (
            await db.execute(
                select(AssignmentRecipient).where(
                    AssignmentRecipient.assignment_id == assignment_id,
                    AssignmentRecipient.student_id == user.id,
                )
            )
        ).scalar_one_or_none()
        assigned_item = (
            await db.execute(
                select(AssignmentItem).where(
                    AssignmentItem.assignment_id == assignment_id,
                    AssignmentItem.question_id == question_id,
                )
            )
        ).scalar_one_or_none()
        if assignment is None or recipient is None or assigned_item is None:
            raise HTTPException(status_code=403, detail="这道题不属于分配给你的当前任务")
    hint_count = max(0, min(int(payload.get("hint_count") or 0), 99))
    input_mode = str(payload.get("input_mode") or "formula")[:24]
    prior_count = (
        await db.execute(
            select(func.count(QuestionAttempt.id)).where(
                QuestionAttempt.user_id == user.id,
                QuestionAttempt.question_id == question_id,
            )
        )
    ).scalar_one()
    diagnostic_prompt = (
        f"题目：{row.get('question')}\n标准答案：{row.get('answer')}\n标准解析：{row.get('explanation')}\n"
        f"学生答案：{answer or '未填写'}\n学生思路：{reasoning or '未填写'}\n"
        "判断学生当前作答。输出JSON：verdict只能是correct、partial、incorrect、needs_review；"
        "feedback先肯定正确部分，再指出第一个问题和下一步，不直接抄完整标准答案；"
        "error_type从概念混淆、条件遗漏、公式选择错误、计算错误、表达不完整、无中选择。"
    )
    result: dict[str, Any] = {}
    try:
        parsed = await LLMClient(name="answer_diagnostic").chat_json(
            [ChatMessage("user", diagnostic_prompt)],
            system=f"你是严谨的概率统计作答诊断教师。只按提供的标准答案评估，不得虚构。{MATH_MARKDOWN_RULE}",
            max_tokens=768,
        )
        if isinstance(parsed, dict):
            result = parsed
    except Exception:
        pass
    allowed = {"correct", "partial", "incorrect", "needs_review"}
    verdict = str(result.get("verdict") or "")
    feedback = str(result.get("feedback") or "").strip()
    error_type = str(result.get("error_type") or "").strip()
    if verdict not in allowed or not feedback:
        normalize = lambda text: re.sub(r"[\s$\\{}，,。；;]", "", text.lower())
        exact = bool(answer) and normalize(answer) == normalize(str(row.get("answer") or ""))
        verdict = "correct" if exact else "needs_review"
        feedback = (
            "答案与题库标准答案一致。请再用一句话说明所用公式或关键依据。"
            if exact
            else "作答已保存。当前无法可靠完成自动等价判断，建议补充关键公式或解题思路后再次提交。"
        )
        error_type = "" if exact else "表达不完整"
    attempt = QuestionAttempt(
        user_id=user.id,
        assignment_id=assignment_id,
        question_id=question_id,
        input_mode=input_mode,
        answer_text=answer or None,
        reasoning=reasoning or None,
        image_name=image_name or None,
        image_data_url=image_data_url or None,
        verdict=verdict,
        feedback=feedback,
        error_type=error_type or None,
        hint_count=hint_count,
        attempt_no=prior_count + 1,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    assignment_completed = False
    if assignment_id and recipient:
        item_count = await db.scalar(
            select(func.count(AssignmentItem.id)).where(AssignmentItem.assignment_id == assignment_id)
        )
        attempted_count = await db.scalar(
            select(func.count(func.distinct(QuestionAttempt.question_id))).where(
                QuestionAttempt.assignment_id == assignment_id,
                QuestionAttempt.user_id == user.id,
            )
        )
        if int(attempted_count or 0) >= int(item_count or 0) > 0:
            recipient.status = "completed"
            recipient.completed_at = datetime.now(timezone.utc)
            await db.commit()
            assignment_completed = True
    return {
        "id": attempt.id,
        "verdict": verdict,
        "feedback": feedback,
        "error_type": error_type or None,
        "attempt_no": attempt.attempt_no,
        "hint_count": hint_count,
        "assignment_id": assignment_id,
        "assignment_completed": assignment_completed,
    }


@router.get("/question-bank/attempts")
async def list_question_attempts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempts = (
        await db.execute(
            select(QuestionAttempt)
            .where(QuestionAttempt.user_id == user.id)
            .order_by(QuestionAttempt.id.desc())
            .limit(100)
        )
    ).scalars().all()
    return [
        {
            "id": item.id,
            "question_id": item.question_id,
            "assignment_id": item.assignment_id,
            "verdict": item.verdict,
            "error_type": item.error_type,
            "hint_count": item.hint_count,
            "attempt_no": item.attempt_no,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in attempts
    ]


@router.post("/question-bank/experiments/runs")
async def save_experiment_run(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    experiment_id = str(payload.get("experiment_id") or "").strip()[:64]
    parameters = payload.get("parameters") or {}
    result_summary = str(payload.get("result_summary") or "").strip()
    observation = str(payload.get("observation") or "").strip()
    if not experiment_id or not isinstance(parameters, dict) or not result_summary:
        raise HTTPException(status_code=400, detail="实验记录不完整")
    record = ExperimentRecord(
        user_id=user.id,
        experiment_id=experiment_id,
        parameters_json=json.dumps(parameters, ensure_ascii=False),
        result_summary=result_summary,
        observation=observation or None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "created_at": record.created_at.isoformat() if record.created_at else None}


@router.get("/question-bank/experiments/runs")
async def list_experiment_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    records = (
        await db.execute(
            select(ExperimentRecord)
            .where(ExperimentRecord.user_id == user.id)
            .order_by(ExperimentRecord.id.desc())
            .limit(100)
        )
    ).scalars().all()
    return [
        {
            "id": item.id,
            "experiment_id": item.experiment_id,
            "parameters": json.loads(item.parameters_json),
            "result_summary": item.result_summary,
            "observation": item.observation,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in records
    ]


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
    return [_stored_plan_payload(item) for item in plans]


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
    question_ids = [str(item).strip().upper() for item in payload.get("question_ids") or [] if str(item).strip()]
    objectives = str(payload.get("objectives") or "").strip()
    duration = max(15, min(int(payload.get("duration") or 45), 180))
    lesson_type = str(payload.get("lesson_type") or "concept")
    learner_profile = str(payload.get("learner_profile") or "mixed")
    if lesson_type not in LESSON_TYPES:
        raise HTTPException(status_code=400, detail="课堂类型无效")
    if learner_profile not in LEARNER_PROFILES:
        raise HTTPException(status_code=400, detail="学情基线无效")
    classroom = None
    classroom_id = payload.get("classroom_id")
    if classroom_id not in (None, ""):
        try:
            classroom_id = int(classroom_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="班级编号无效") from exc
        classroom = (
            await db.execute(
                select(Classroom).where(Classroom.id == classroom_id, Classroom.teacher_id == user.id)
            )
        ).scalar_one_or_none()
        if classroom is None:
            raise HTTPException(status_code=404, detail="班级不存在或不属于当前教师")
    else:
        classroom_id = None
    missing_ids = [question_id for question_id in question_ids if get_question(question_id) is None]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"题库中不存在：{'、'.join(missing_ids[:5])}")
    retrieved = retrieve_context(topic or " ".join(question_ids), question_ids, limit=30)
    explicit_rows = [row for question_id in question_ids if (row := get_question(question_id))]
    rows = []
    seen_ids: set[str] = set()
    for row in [*explicit_rows, *select_layered_questions(retrieved, limit=12)]:
        if row["ID"] not in seen_ids:
            rows.append(row)
            seen_ids.add(row["ID"])
        if len(rows) >= 12:
            break
    if not rows:
        raise HTTPException(status_code=400, detail="请填写教学主题或选择题目")
    attempts: list[QuestionAttempt] = []
    if classroom is not None:
        attempts = (
            await db.execute(
                select(QuestionAttempt)
                .join(LearningAssignment, LearningAssignment.id == QuestionAttempt.assignment_id)
                .where(LearningAssignment.classroom_id == classroom.id)
                .order_by(QuestionAttempt.id.desc())
                .limit(2000)
            )
        ).scalars().all()
    insights = build_teaching_insights(rows, [_attempt_analytics_payload(item) for item in attempts])
    generated = build_teaching_package(
        topic=topic or "概率论与数理统计",
        duration=duration,
        objectives=objectives,
        rows=rows,
        insights=insights,
        lesson_type=lesson_type,
        learner_profile=learner_profile,
        classroom_name=classroom.name if classroom else None,
    )
    content = generated["teacher_content"]
    student_content = generated["student_content"]
    package = generated["manifest"]
    model = "curriculum-engine-v2"
    selected_ids = [row["ID"] for row in rows]
    plan = TeachingPlan(
        user_id=user.id,
        classroom_id=classroom_id,
        title=f"{topic or '概率统计'} · {duration} 分钟",
        topic=topic or "概率论与数理统计",
        duration=duration,
        lesson_type=lesson_type,
        learner_profile=learner_profile,
        objectives=objectives or None,
        question_ids_json=json.dumps(selected_ids, ensure_ascii=False),
        content=content,
        student_content=student_content,
        package_json=json.dumps(package, ensure_ascii=False),
        model=model,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {
        "id": plan.id,
        "title": plan.title,
        "topic": plan.topic,
        "duration": plan.duration,
        "classroom_id": plan.classroom_id,
        "lesson_type": lesson_type,
        "learner_profile": learner_profile,
        "content": content,
        "student_content": student_content,
        "question_ids": selected_ids,
        "layers": _layer_payload(selected_ids),
        "package": package,
        "insights": insights,
        "model": model,
    }
