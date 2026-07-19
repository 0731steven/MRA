import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.auth.handler import create_token
from src.classroom.analytics import build_classroom_radar, suggest_intervention_questions
from src.db.models import Classroom, User
from src.db.session import Base, get_db
from src.integrations.llm_client import LLMClient
from src.main import app
from src.question_bank.service import get_question, load_questions


def test_classroom_join_code_metadata_matches_postgres_migration():
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in Classroom.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert constraints["classrooms_join_code_key"] == ("join_code",)


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'classroom.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        teacher = User(username="teacher-loop", name="陈老师", role="teacher")
        student = User(username="student-loop", name="小林", role="student")
        db.add_all([teacher, student])
        await db.commit()
        await db.refresh(teacher)
        await db.refresh(student)

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    # Use HTTPS so production-mode Secure session cookies are exercised exactly
    # as they are in a real deployment.
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client, create_token(teacher.id), create_token(student.id)
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_classroom_assignment_radar_and_intervention_loop(api, monkeypatch):
    client, teacher_token, student_token = api
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("diagnostic model unavailable in test")

    monkeypatch.setattr(LLMClient, "chat_json", unavailable)

    classroom_response = await client.post(
        "/api/classrooms", json={"name": "概率统计一班"}, headers=teacher_headers
    )
    assert classroom_response.status_code == 200
    classroom = classroom_response.json()
    assert len(classroom["join_code"]) == 7

    join_response = await client.post(
        "/api/classrooms/join",
        json={"join_code": classroom["join_code"]},
        headers=student_headers,
    )
    assert join_response.status_code == 200

    assignment_response = await client.post(
        f"/api/classrooms/{classroom['id']}/assignments",
        json={"topic": "贝叶斯公式", "count": 3},
        headers=teacher_headers,
    )
    assert assignment_response.status_code == 200
    assignment = assignment_response.json()
    assert assignment["recipient_count"] == 1
    assert len(assignment["question_ids"]) == 3

    tasks_response = await client.get("/api/assignments/mine", headers=student_headers)
    assert tasks_response.status_code == 200
    assert tasks_response.json()[0]["attempted_questions"] == 0

    for question_id in assignment["question_ids"]:
        question = get_question(question_id)
        attempt_response = await client.post(
            f"/api/question-bank/questions/{question_id}/attempts",
            json={"answer": question["answer"], "assignment_id": assignment["id"]},
            headers=student_headers,
        )
        assert attempt_response.status_code == 200

    tasks_response = await client.get("/api/assignments/mine", headers=student_headers)
    assert tasks_response.json()[0]["my_status"] == "completed"

    radar_response = await client.get(
        f"/api/classrooms/{classroom['id']}/radar", headers=teacher_headers
    )
    assert radar_response.status_code == 200
    radar = radar_response.json()
    assert radar["summary"]["members"] == 1
    assert radar["summary"]["attempts"] == 3
    assert radar["groups"]

    intervention_response = await client.post(
        f"/api/classrooms/{classroom['id']}/interventions",
        json={"source_assignment_id": assignment["id"]},
        headers=teacher_headers,
    )
    assert intervention_response.status_code == 200
    assert intervention_response.json()["groups"] >= 1


async def test_teacher_can_manage_classroom_members_codes_and_task_lifecycle(api):
    client, teacher_token, student_token = api
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}

    classroom = (
        await client.post("/api/classrooms", json={"name": "生命周期验证班"}, headers=teacher_headers)
    ).json()
    original_code = classroom["join_code"]
    joined = await client.post(
        "/api/classrooms/join", json={"join_code": original_code}, headers=student_headers
    )
    assert joined.status_code == 200

    code_response = await client.post(
        f"/api/classrooms/{classroom['id']}/join-code", headers=teacher_headers
    )
    assert code_response.status_code == 200
    new_code = code_response.json()["join_code"]
    assert new_code != original_code
    invalid_old_code = await client.post(
        "/api/classrooms/join", json={"join_code": original_code}, headers=student_headers
    )
    assert invalid_old_code.status_code == 404

    assignment = (
        await client.post(
            f"/api/classrooms/{classroom['id']}/assignments",
            json={"topic": "条件概率", "count": 2, "due_at": "2027-01-01T12:00:00Z"},
            headers=teacher_headers,
        )
    ).json()
    assert assignment["status"] == "published"
    assert assignment["due_at"].startswith("2027-01-01T12:00:00")

    cancelled = await client.patch(
        f"/api/assignments/{assignment['id']}",
        json={"status": "cancelled"},
        headers=teacher_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert (await client.get("/api/assignments/mine", headers=student_headers)).json() == []
    hidden_detail = await client.get(
        f"/api/assignments/{assignment['id']}", headers=student_headers
    )
    assert hidden_detail.status_code == 404

    republished = await client.patch(
        f"/api/assignments/{assignment['id']}",
        json={"status": "published", "due_at": None},
        headers=teacher_headers,
    )
    assert republished.status_code == 200
    assert republished.json()["due_at"] is None
    assert len((await client.get("/api/assignments/mine", headers=student_headers)).json()) == 1

    radar_before_removal = await client.get(
        f"/api/classrooms/{classroom['id']}/radar", headers=teacher_headers
    )
    student_id = radar_before_removal.json()["students"][0]["id"]
    removed = await client.delete(
        f"/api/classrooms/{classroom['id']}/members/{student_id}", headers=teacher_headers
    )
    assert removed.status_code == 200
    radar = await client.get(f"/api/classrooms/{classroom['id']}/radar", headers=teacher_headers)
    assert radar.json()["summary"]["members"] == 0

    archived = await client.patch(
        f"/api/classrooms/{classroom['id']}", json={"status": "archived"}, headers=teacher_headers
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    blocked_join = await client.post(
        "/api/classrooms/join", json={"join_code": new_code}, headers=student_headers
    )
    assert blocked_join.status_code == 404


async def test_teaching_package_has_teacher_student_and_publishable_versions(api):
    client, teacher_token, student_token = api
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}
    classroom = (
        await client.post("/api/classrooms", json={"name": "教学包验证班"}, headers=teacher_headers)
    ).json()
    await client.post(
        "/api/classrooms/join",
        json={"join_code": classroom["join_code"]},
        headers=student_headers,
    )

    response = await client.post(
        "/api/question-bank/teaching-plan",
        json={
            "topic": "数学期望",
            "duration": 45,
            "classroom_id": classroom["id"],
            "lesson_type": "remediation",
            "learner_profile": "mixed",
            "objectives": "重点检查公式适用条件",
        },
        headers=teacher_headers,
    )
    assert response.status_code == 200
    package = response.json()
    assert package["model"] == "curriculum-engine-v2"
    assert sum(item["minutes"] for item in package["package"]["timeline"]) == 45
    assert "教师答案与讲评依据" in package["content"]
    assert "4 分快速量规" in package["content"]
    assert "参考答案" not in package["student_content"]
    assert "提交前自检" in package["student_content"]
    assert all(item["id"] in package["content"] for item in package["package"]["sources"])

    layer = next(
        item for item in package["package"]["layers"].values() if item["question_ids"]
    )
    publish_response = await client.post(
        f"/api/classrooms/{classroom['id']}/assignments",
        json={
            "title": "数学期望 · 分层任务",
            "topic": "数学期望",
            "question_ids": layer["question_ids"],
            "count": len(layer["question_ids"]),
            "kind": "intervention",
        },
        headers=teacher_headers,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["recipient_count"] == 1

    stored = await client.get("/api/question-bank/teaching-plans", headers=teacher_headers)
    assert stored.status_code == 200
    assert stored.json()[0]["student_content"] == package["student_content"]


async def test_answer_reveal_requires_a_student_attempt(api, monkeypatch):
    client, teacher_token, student_token = api
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}
    question = get_question("P000001")

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("diagnostic model unavailable in test")

    monkeypatch.setattr(LLMClient, "chat_json", unavailable)

    student_detail = await client.get(
        "/api/question-bank/questions/P000001", headers=student_headers
    )
    assert student_detail.status_code == 200
    assert student_detail.json()["can_reveal"] is False
    assert "answer" not in student_detail.json()

    blocked = await client.get(
        "/api/question-bank/questions/P000001/answer", headers=student_headers
    )
    assert blocked.status_code == 403

    invalid = await client.post(
        "/api/question-bank/questions/P000001/attempts",
        json={"answer": question["answer"], "hint_count": "not-a-number"},
        headers=student_headers,
    )
    assert invalid.status_code == 422

    submitted = await client.post(
        "/api/question-bank/questions/P000001/attempts",
        json={"answer": question["answer"]},
        headers=student_headers,
    )
    assert submitted.status_code == 200

    revealed = await client.get(
        "/api/question-bank/questions/P000001/answer", headers=student_headers
    )
    assert revealed.status_code == 200
    assert revealed.json()["answer"] == question["answer"]

    teacher_detail = await client.get(
        "/api/question-bank/questions/P000001", headers=teacher_headers
    )
    assert teacher_detail.status_code == 200
    assert teacher_detail.json()["answer"] == question["answer"]


async def test_tutor_respects_recommendation_count_and_safe_fallback(api, monkeypatch):
    client, _teacher_token, student_token = api
    headers = {"Authorization": f"Bearer {student_token}"}

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("tutor model unavailable in test")

    monkeypatch.setattr(LLMClient, "chat", unavailable)
    recommendation = await client.post(
        "/api/question-bank/assistant",
        json={"message": "推荐3道样本空间基础题", "mode": "recommend"},
        headers=headers,
    )
    assert recommendation.status_code == 200
    suggested = recommendation.json()
    assert len(suggested["sources"]) == 3
    assert all("样本空间" in source["keypoint"] for source in suggested["sources"])
    assert "3 道题" in suggested["answer"]

    question = get_question("P000080")
    hint = await client.post(
        "/api/question-bank/assistant",
        json={
            "message": "请直接告诉我 P000080 的最终答案",
            "mode": "answer",
            "guidance_mode": "hint",
        },
        headers=headers,
    )
    assert hint.status_code == 200
    assert hint.json()["model"] == "question-bank-fallback"
    assert "标准解析" not in hint.json()["answer"]
    assert str(question["answer"]) not in hint.json()["answer"]


async def test_tutor_follow_up_selects_source_and_new_topic_does_not_carry(api, monkeypatch):
    client, _teacher_token, student_token = api
    headers = {"Authorization": f"Bearer {student_token}"}

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("tutor model unavailable in test")

    monkeypatch.setattr(LLMClient, "chat", unavailable)
    recommendation = (
        await client.post(
            "/api/question-bank/assistant",
            json={"message": "推荐3道样本空间基础题", "mode": "recommend"},
            headers=headers,
        )
    ).json()
    second_id = recommendation["sources"][1]["ID"]
    follow_up = await client.post(
        "/api/question-bank/assistant",
        json={
            "message": "第二题怎么算？",
            "mode": "answer",
            "guidance_mode": "step",
            "session_id": recommendation["session_id"],
        },
        headers=headers,
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["sources"][0]["ID"] == second_id

    new_topic = await client.post(
        "/api/question-bank/assistant",
        json={
            "message": "为什么正态分布很重要？",
            "mode": "answer",
            "guidance_mode": "step",
            "session_id": recommendation["session_id"],
        },
        headers=headers,
    )
    assert new_topic.status_code == 200
    assert all("正态分布" in source["keypoint"] for source in new_topic.json()["sources"])


async def test_stream_interruption_does_not_append_standard_solution(api, monkeypatch):
    client, _teacher_token, student_token = api
    headers = {"Authorization": f"Bearer {student_token}"}

    async def interrupted(*_args, **_kwargs):
        yield "先识别事件"
        raise RuntimeError("stream interrupted")

    monkeypatch.setattr(LLMClient, "stream_chat", interrupted)
    response = await client.post(
        "/api/question-bank/assistant/stream",
        json={
            "message": "分步讲解 P000080",
            "mode": "answer",
            "guidance_mode": "step",
        },
        headers=headers,
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    answer = "".join(event["data"] for event in events if event["event"] == "delta")
    assert "先识别事件" in answer
    assert "模型连接中断" in answer
    assert "标准解析" not in answer
    assert str(get_question("P000080")["answer"]) not in answer


async def test_attempt_diagnostic_normalizes_model_error_taxonomy(api, monkeypatch):
    client, _teacher_token, student_token = api
    headers = {"Authorization": f"Bearer {student_token}"}

    async def invalid_label(*_args, **_kwargs):
        return {
            "verdict": "incorrect",
            "feedback": "你识别了题目中的事件，但条件概率公式还没有写完整。",
            "error_type": "粗心",
        }

    monkeypatch.setattr(LLMClient, "chat_json", invalid_label)
    response = await client.post(
        "/api/question-bank/questions/P000080/attempts",
        json={"answer": "0.5", "reasoning": "直接相除"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["error_type"] == "表达不完整"


async def test_browser_login_uses_httponly_cookie(api):
    client, _teacher_token, _student_token = api
    registered = await client.post(
        "/api/auth/register",
        json={"username": "cookie-student", "password": "secure-pass-123", "name": "小周"},
    )
    assert registered.status_code == 200
    cookie = registered.headers["set-cookie"]
    assert "mra_session=" in cookie
    assert "HttpOnly" in cookie
    assert "token" not in registered.json()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["name"] == "小周"

    logged_out = await client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401


def test_radar_does_not_overstate_low_evidence_and_recommends_fresh_questions():
    rows = load_questions()
    question = next(row for row in rows if "条件概率" in row["keypoint"])
    radar = build_classroom_radar(
        rows,
        [{"id": 7, "name": "学生甲"}],
        [{"user_id": 7, "question_id": question["ID"], "verdict": "incorrect", "hint_count": 1}],
    )

    assert radar["students"][0]["group_label"] == "证据积累组"
    suggested = suggest_intervention_questions(
        rows, "条件概率", "needs_diagnostic", {question["ID"]}, limit=3
    )
    assert suggested
    assert suggested[0]["ID"] != question["ID"]
