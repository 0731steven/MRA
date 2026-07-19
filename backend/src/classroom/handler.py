from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.handler import get_current_user
from ..db.models import (
    AssignmentItem,
    AssignmentRecipient,
    Classroom,
    ClassroomMembership,
    LearningAssignment,
    QuestionAttempt,
    User,
)
from ..db.session import get_db
from ..question_bank.analytics import select_layered_questions
from ..question_bank.service import compact_question, get_question, load_questions, retrieve_context
from .analytics import build_classroom_radar, suggest_intervention_questions


router = APIRouter()
JOIN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class ClassroomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    course_name: str = Field(default="概率论与数理统计", max_length=160)


class ClassroomJoinRequest(BaseModel):
    join_code: str = Field(min_length=1, max_length=12)


class ClassroomUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    course_name: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["active", "archived"] | None = None


class AssignmentCreateRequest(BaseModel):
    topic: str = Field(default="", max_length=160)
    title: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=3000)
    question_ids: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal["diagnostic", "intervention", "retest"] = "diagnostic"
    count: int = Field(default=5, ge=1, le=8)
    due_at: datetime | None = None


class InterventionCreateRequest(BaseModel):
    source_assignment_id: int | None = Field(default=None, gt=0)


class AssignmentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=3000)
    due_at: datetime | None = None
    status: Literal["published", "cancelled", "archived"] | None = None


def _require_teacher(user: User) -> None:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可以管理班级")


async def _owned_classroom(db: AsyncSession, classroom_id: int, teacher_id: int) -> Classroom:
    classroom = (
        await db.execute(
            select(Classroom).where(Classroom.id == classroom_id, Classroom.teacher_id == teacher_id)
        )
    ).scalar_one_or_none()
    if classroom is None:
        raise HTTPException(status_code=404, detail="班级不存在或不属于当前教师")
    return classroom


async def _classroom_for_member(db: AsyncSession, classroom_id: int, student_id: int) -> Classroom:
    classroom = (
        await db.execute(
            select(Classroom)
            .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
            .where(Classroom.id == classroom_id, ClassroomMembership.student_id == student_id)
        )
    ).scalar_one_or_none()
    if classroom is None:
        raise HTTPException(status_code=404, detail="你尚未加入这个班级")
    return classroom


async def _owned_assignment(db: AsyncSession, assignment_id: int, teacher_id: int) -> LearningAssignment:
    assignment = (
        await db.execute(
            select(LearningAssignment)
            .join(Classroom, Classroom.id == LearningAssignment.classroom_id)
            .where(LearningAssignment.id == assignment_id, Classroom.teacher_id == teacher_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前教师")
    return assignment


async def _unique_join_code(db: AsyncSession) -> str:
    for _ in range(12):
        code = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(7))
        exists = await db.scalar(select(func.count(Classroom.id)).where(Classroom.join_code == code))
        if not exists:
            return code
    raise HTTPException(status_code=503, detail="暂时无法生成班级码，请稍后重试")


def _parse_due_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="截止时间格式无效") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _assignment_payload(db: AsyncSession, assignment: LearningAssignment, user_id: int | None = None) -> dict[str, Any]:
    items = (
        await db.execute(
            select(AssignmentItem)
            .where(AssignmentItem.assignment_id == assignment.id)
            .order_by(AssignmentItem.position, AssignmentItem.id)
        )
    ).scalars().all()
    recipient_count = await db.scalar(
        select(func.count(AssignmentRecipient.id)).where(AssignmentRecipient.assignment_id == assignment.id)
    )
    completed_count = await db.scalar(
        select(func.count(AssignmentRecipient.id)).where(
            AssignmentRecipient.assignment_id == assignment.id,
            AssignmentRecipient.status == "completed",
        )
    )
    recipient = None
    if user_id is not None:
        recipient = (
            await db.execute(
                select(AssignmentRecipient).where(
                    AssignmentRecipient.assignment_id == assignment.id,
                    AssignmentRecipient.student_id == user_id,
                )
            )
        ).scalar_one_or_none()
    return {
        "id": assignment.id,
        "classroom_id": assignment.classroom_id,
        "source_assignment_id": assignment.source_assignment_id,
        "title": assignment.title,
        "description": assignment.description,
        "kind": assignment.kind,
        "topic": assignment.topic,
        "status": assignment.status,
        "question_ids": [item.question_id for item in items],
        "recipient_count": int(recipient_count or 0),
        "completed_count": int(completed_count or 0),
        "my_status": recipient.status if recipient else None,
        "group_label": recipient.group_label if recipient else None,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
    }


async def _radar_data(db: AsyncSession, classroom: Classroom) -> dict[str, Any]:
    students = (
        await db.execute(
            select(User)
            .join(ClassroomMembership, ClassroomMembership.student_id == User.id)
            .where(ClassroomMembership.classroom_id == classroom.id)
            .order_by(User.name, User.id)
        )
    ).scalars().all()
    assignments = (
        await db.execute(
            select(LearningAssignment)
            .where(LearningAssignment.classroom_id == classroom.id)
            .order_by(LearningAssignment.id.desc())
        )
    ).scalars().all()
    assignment_ids = [item.id for item in assignments]
    assignment_kind = {item.id: item.kind for item in assignments}
    attempts: list[QuestionAttempt] = []
    if assignment_ids:
        attempts = (
            await db.execute(
                select(QuestionAttempt)
                .where(QuestionAttempt.assignment_id.in_(assignment_ids))
                .order_by(QuestionAttempt.id.desc())
                .limit(5000)
            )
        ).scalars().all()
    radar = build_classroom_radar(
        load_questions(),
        [{"id": item.id, "name": item.name} for item in students],
        [
            {
                "user_id": item.user_id,
                "question_id": item.question_id,
                "verdict": item.verdict,
                "error_type": item.error_type,
                "hint_count": item.hint_count,
                "attempt_no": item.attempt_no,
                "assignment_kind": assignment_kind.get(item.assignment_id),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in attempts
        ],
    )
    recent = [await _assignment_payload(db, assignment) for assignment in assignments[:8]]
    radar["classroom"] = {
        "id": classroom.id,
        "name": classroom.name,
        "course_name": classroom.course_name,
        "join_code": classroom.join_code,
        "status": classroom.status,
    }
    radar["assignments"] = recent
    return radar


@router.get("/classrooms")
async def list_classrooms(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "teacher":
        classrooms = (
            await db.execute(
                select(Classroom).where(Classroom.teacher_id == user.id).order_by(Classroom.id.desc())
            )
        ).scalars().all()
    else:
        classrooms = (
            await db.execute(
                select(Classroom)
                .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
                .where(ClassroomMembership.student_id == user.id)
                .order_by(Classroom.id.desc())
            )
        ).scalars().all()
    result = []
    for classroom in classrooms:
        members = await db.scalar(
            select(func.count(ClassroomMembership.id)).where(ClassroomMembership.classroom_id == classroom.id)
        )
        assignments = await db.scalar(
            select(func.count(LearningAssignment.id)).where(LearningAssignment.classroom_id == classroom.id)
        )
        result.append(
            {
                "id": classroom.id,
                "name": classroom.name,
                "course_name": classroom.course_name,
                "join_code": classroom.join_code if user.role == "teacher" else None,
                "status": classroom.status,
                "members": int(members or 0),
                "assignments": int(assignments or 0),
                "created_at": classroom.created_at.isoformat() if classroom.created_at else None,
            }
        )
    return result


@router.post("/classrooms")
async def create_classroom(
    payload: ClassroomCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    name = payload.name.strip()
    course_name = payload.course_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入班级名称")
    classroom = Classroom(
        teacher_id=user.id,
        name=name[:160],
        course_name=course_name[:160] or "概率论与数理统计",
        join_code=await _unique_join_code(db),
    )
    db.add(classroom)
    await db.commit()
    await db.refresh(classroom)
    return {
        "id": classroom.id,
        "name": classroom.name,
        "course_name": classroom.course_name,
        "join_code": classroom.join_code,
        "members": 0,
        "assignments": 0,
        "status": classroom.status,
    }


@router.patch("/classrooms/{classroom_id}")
async def update_classroom(
    classroom_id: int,
    payload: ClassroomUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    classroom = await _owned_classroom(db, classroom_id, user.id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="班级名称不能为空")
        classroom.name = name
    if payload.course_name is not None:
        course_name = payload.course_name.strip()
        if not course_name:
            raise HTTPException(status_code=400, detail="课程名称不能为空")
        classroom.course_name = course_name
    if payload.status is not None:
        classroom.status = payload.status
    await db.commit()
    await db.refresh(classroom)
    return {
        "id": classroom.id,
        "name": classroom.name,
        "course_name": classroom.course_name,
        "join_code": classroom.join_code,
        "status": classroom.status,
    }


@router.post("/classrooms/{classroom_id}/join-code")
async def regenerate_join_code(
    classroom_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    classroom = await _owned_classroom(db, classroom_id, user.id)
    classroom.join_code = await _unique_join_code(db)
    await db.commit()
    await db.refresh(classroom)
    return {"id": classroom.id, "join_code": classroom.join_code, "status": classroom.status}


@router.delete("/classrooms/{classroom_id}/members/{student_id}")
async def remove_classroom_member(
    classroom_id: int,
    student_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    await _owned_classroom(db, classroom_id, user.id)
    membership = (
        await db.execute(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom_id,
                ClassroomMembership.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="学生不在这个班级中")
    await db.delete(membership)
    await db.commit()
    return {"removed": True, "student_id": student_id}


@router.post("/classrooms/join")
async def join_classroom(
    payload: ClassroomJoinRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "student":
        raise HTTPException(status_code=403, detail="教师账号不能通过班级码加入班级")
    code = payload.join_code.strip().upper()
    classroom = (
        await db.execute(select(Classroom).where(Classroom.join_code == code, Classroom.status == "active"))
    ).scalar_one_or_none()
    if classroom is None:
        raise HTTPException(status_code=404, detail="班级码无效，请向教师确认后重试")
    existing = (
        await db.execute(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom.id,
                ClassroomMembership.student_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ClassroomMembership(classroom_id=classroom.id, student_id=user.id))
        await db.commit()
    return {"id": classroom.id, "name": classroom.name, "course_name": classroom.course_name, "joined": True}


@router.get("/classrooms/{classroom_id}/radar")
async def classroom_radar(
    classroom_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    classroom = await _owned_classroom(db, classroom_id, user.id)
    return await _radar_data(db, classroom)


@router.post("/classrooms/{classroom_id}/assignments")
async def create_assignment(
    classroom_id: int,
    payload: AssignmentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    classroom = await _owned_classroom(db, classroom_id, user.id)
    if classroom.status != "active":
        raise HTTPException(status_code=409, detail="班级已归档，请先恢复班级再发布任务")
    members = (
        await db.execute(
            select(ClassroomMembership.student_id).where(ClassroomMembership.classroom_id == classroom.id)
        )
    ).scalars().all()
    if not members:
        raise HTTPException(status_code=400, detail="班级还没有学生，请先让学生使用班级码加入")
    topic = payload.topic.strip()
    title = (payload.title or f"{topic or '指定题目'} · 课堂诊断").strip()
    explicit_ids = [item.strip().upper() for item in payload.question_ids]
    kind = payload.kind
    if not topic and not explicit_ids:
        raise HTTPException(status_code=400, detail="请输入诊断主题或指定题号")
    count = payload.count
    explicit_rows = [row for question_id in explicit_ids if (row := get_question(question_id))]
    retrieved = retrieve_context(topic or " ".join(explicit_ids), explicit_ids, limit=30)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*explicit_rows, *select_layered_questions(retrieved, limit=count)]:
        if row["ID"] not in seen:
            selected.append(row)
            seen.add(row["ID"])
        if len(selected) >= count:
            break
    if not selected:
        raise HTTPException(status_code=400, detail="当前题库没有找到匹配题目，请换一个更具体的知识点")
    assignment = LearningAssignment(
        classroom_id=classroom.id,
        created_by=user.id,
        title=title[:180],
        description=payload.description or "完成后，班级认知雷达会依据作答、错误类型和提示使用情况更新。",
        kind=kind,
        topic=(topic or "根据指定题目诊断")[:160],
        status="published",
        due_at=_parse_due_at(payload.due_at),
    )
    db.add(assignment)
    await db.flush()
    for position, row in enumerate(selected):
        db.add(AssignmentItem(assignment_id=assignment.id, question_id=row["ID"], position=position))
    for student_id in members:
        db.add(AssignmentRecipient(assignment_id=assignment.id, student_id=student_id))
    await db.commit()
    await db.refresh(assignment)
    return await _assignment_payload(db, assignment)


@router.post("/classrooms/{classroom_id}/interventions")
async def create_adaptive_interventions(
    classroom_id: int,
    payload: InterventionCreateRequest = Body(default=InterventionCreateRequest()),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    classroom = await _owned_classroom(db, classroom_id, user.id)
    if classroom.status != "active":
        raise HTTPException(status_code=409, detail="班级已归档，请先恢复班级再发布任务")
    radar = await _radar_data(db, classroom)
    if not radar["groups"]:
        raise HTTPException(status_code=400, detail="班级暂无学生，不能生成干预任务")
    source_assignment_id = payload.source_assignment_id
    if source_assignment_id:
        source = (
            await db.execute(
                select(LearningAssignment).where(
                    LearningAssignment.id == source_assignment_id,
                    LearningAssignment.classroom_id == classroom.id,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=400, detail="来源任务不属于当前班级")
    created: list[LearningAssignment] = []
    all_rows = load_questions()
    classroom_assignment_ids = [item["id"] for item in radar["assignments"]]
    if radar["assignments"]:
        all_class_assignments = (
            await db.execute(
                select(LearningAssignment.id).where(LearningAssignment.classroom_id == classroom.id)
            )
        ).scalars().all()
        classroom_assignment_ids = list(all_class_assignments)
    for group in radar["groups"][:10]:
        student_ids = [int(item) for item in group["student_ids"]]
        prior_ids = set(
            (
                await db.execute(
                    select(QuestionAttempt.question_id).where(
                        QuestionAttempt.user_id.in_(student_ids),
                        QuestionAttempt.assignment_id.in_(classroom_assignment_ids),
                    )
                )
            ).scalars().all()
        )
        questions = suggest_intervention_questions(
            all_rows,
            str(group["focus"]),
            str(group["type"]),
            prior_ids,
            limit=3,
        )
        if not questions:
            continue
        kind = "diagnostic" if group["type"] == "needs_diagnostic" else "retest" if group["type"] == "transfer_ready" else "intervention"
        assignment = LearningAssignment(
            classroom_id=classroom.id,
            created_by=user.id,
            source_assignment_id=source_assignment_id,
            title=f"{group['label']} · {group['focus']}",
            description=f"{group['strategy']}最后一道题作为无提示迁移验证，完成后自动回写班级认知雷达。",
            kind=kind,
            topic=str(group["focus"])[:160],
            status="published",
        )
        db.add(assignment)
        await db.flush()
        for position, row in enumerate(questions):
            db.add(AssignmentItem(assignment_id=assignment.id, question_id=row["ID"], position=position))
        for student_id in student_ids:
            db.add(
                AssignmentRecipient(
                    assignment_id=assignment.id,
                    student_id=student_id,
                    group_label=str(group["label"])[:80],
                )
            )
        created.append(assignment)
    if not created:
        raise HTTPException(status_code=400, detail="当前题库没有足够题目生成干预任务")
    await db.commit()
    payloads = [await _assignment_payload(db, assignment) for assignment in created]
    return {
        "created": payloads,
        "groups": len(created),
        "students": sum(item["recipient_count"] for item in payloads),
    }


@router.get("/assignments/mine")
async def my_assignments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "student":
        raise HTTPException(status_code=403, detail="教师请在班级认知雷达中查看任务")
    assignments = (
        await db.execute(
            select(LearningAssignment)
            .join(AssignmentRecipient, AssignmentRecipient.assignment_id == LearningAssignment.id)
            .where(AssignmentRecipient.student_id == user.id, LearningAssignment.status == "published")
            .order_by(LearningAssignment.id.desc())
        )
    ).scalars().all()
    classroom_ids = {item.classroom_id for item in assignments}
    classrooms = {}
    if classroom_ids:
        classroom_rows = (
            await db.execute(select(Classroom).where(Classroom.id.in_(classroom_ids)))
        ).scalars().all()
        classrooms = {item.id: item.name for item in classroom_rows}
    result = []
    for assignment in assignments:
        item = await _assignment_payload(db, assignment, user.id)
        item["classroom_name"] = classrooms.get(assignment.classroom_id)
        attempted = await db.scalar(
            select(func.count(func.distinct(QuestionAttempt.question_id))).where(
                QuestionAttempt.assignment_id == assignment.id,
                QuestionAttempt.user_id == user.id,
            )
        )
        item["attempted_questions"] = int(attempted or 0)
        result.append(item)
    return result


@router.patch("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_teacher(user)
    assignment = await _owned_assignment(db, assignment_id, user.id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="任务名称不能为空")
        assignment.title = title
    if payload.description is not None:
        assignment.description = payload.description.strip()
    if "due_at" in payload.model_fields_set:
        assignment.due_at = _parse_due_at(payload.due_at)
    if payload.status is not None:
        assignment.status = payload.status
    await db.commit()
    await db.refresh(assignment)
    return await _assignment_payload(db, assignment)


@router.get("/assignments/{assignment_id}")
async def assignment_detail(
    assignment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    assignment = (
        await db.execute(select(LearningAssignment).where(LearningAssignment.id == assignment_id))
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if user.role == "teacher":
        await _owned_classroom(db, assignment.classroom_id, user.id)
    else:
        if assignment.status != "published":
            raise HTTPException(status_code=404, detail="任务已撤回或归档")
        recipient = (
            await db.execute(
                select(AssignmentRecipient).where(
                    AssignmentRecipient.assignment_id == assignment.id,
                    AssignmentRecipient.student_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if recipient is None:
            raise HTTPException(status_code=404, detail="这项任务没有分配给你")
    payload = await _assignment_payload(db, assignment, user.id if user.role == "student" else None)
    classroom = await db.get(Classroom, assignment.classroom_id)
    payload["classroom_name"] = classroom.name if classroom else None
    payload["questions"] = [
        compact_question(row, include_answer=user.role == "teacher")
        for question_id in payload["question_ids"]
        if (row := get_question(question_id))
    ]
    return payload


@router.get("/classrooms/{classroom_id}")
async def classroom_detail(
    classroom_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    classroom = (
        await _owned_classroom(db, classroom_id, user.id)
        if user.role == "teacher"
        else await _classroom_for_member(db, classroom_id, user.id)
    )
    return {
        "id": classroom.id,
        "name": classroom.name,
        "course_name": classroom.course_name,
        "join_code": classroom.join_code if user.role == "teacher" else None,
        "status": classroom.status,
    }
