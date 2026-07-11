from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ..auth.handler import get_current_user
from ..db.models import User
from ..integrations.llm_client import ChatMessage, LLMClient
from .service import bank_stats, compact_question, get_question, retrieve_context, search_questions


router = APIRouter()


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


@router.get("/question-bank/stats")
async def stats(_user: User = Depends(get_current_user)):
    return bank_stats()


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
async def assistant(payload: dict = Body(...), user: User = Depends(get_current_user)):
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入问题")
    mode = str(payload.get("mode") or "answer")
    question_ids = [str(item) for item in payload.get("question_ids") or []]
    context_rows = retrieve_context(message, question_ids, limit=6)
    if not context_rows:
        return {
            "answer": "我暂时没有在当前题库中找到足够接近的题目。你可以换一个知识点、题号，或补充更完整的题干。",
            "sources": [],
            "model": "retrieval-only",
        }

    if mode == "recommend":
        intro = "根据你的要求，我从题库中筛选了这些题。建议先独立作答，再查看解析："
        return {
            "answer": intro,
            "sources": [compact_question(row, include_answer=False) for row in context_rows],
            "model": "question-bank-retrieval",
        }

    system = (
        "你是概率论与数理统计教学助手。必须以给定题库资料为核心作答，不得虚构题号、题干、答案或结论。"
        "学生提问时采用启发式讲解：先判断考点，再分步骤推导，指出易错点，最后给出结论；不要只复述答案。"
        "如果资料不足，要明确说明。数学公式使用 Markdown LaTeX。引用题库内容时标明题号，如【P000001】。"
    )
    if _is_teacher(user):
        system += "当前用户是教师，可以补充教学目标、课堂提问建议和分层讲解方法。"
    try:
        answer = await LLMClient(name="question_bank_tutor").chat(
            [ChatMessage("user", f"题库资料：\n{_context_text(context_rows)}\n\n用户问题：{message}")],
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
    return {
        "answer": answer,
        "sources": [compact_question(row, include_answer=False) for row in context_rows],
        "model": model,
    }


@router.post("/question-bank/teaching-plan")
async def teaching_plan(payload: dict = Body(...), user: User = Depends(get_current_user)):
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
    return {"content": content, "question_ids": [row["ID"] for row in rows], "model": model}
