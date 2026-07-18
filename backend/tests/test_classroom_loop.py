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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
