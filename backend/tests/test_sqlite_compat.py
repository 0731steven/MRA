from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.db.compat import ensure_local_sqlite_compatibility


async def test_old_sqlite_question_attempts_table_is_upgraded_additively(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")

    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE learning_assignments (id INTEGER PRIMARY KEY)"))
        await connection.execute(text("CREATE TABLE classrooms (id INTEGER PRIMARY KEY)"))
        await connection.execute(text("CREATE TABLE question_attempts (id INTEGER PRIMARY KEY, question_id VARCHAR(16))"))
        await connection.execute(text("CREATE TABLE teaching_plans (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"))

        await ensure_local_sqlite_compatibility(connection)
        await ensure_local_sqlite_compatibility(connection)

        def schema(sync_connection):
            inspector = inspect(sync_connection)
            return (
                {column["name"] for column in inspector.get_columns("question_attempts")},
                {index["name"] for index in inspector.get_indexes("question_attempts")},
                {column["name"] for column in inspector.get_columns("teaching_plans")},
                {index["name"] for index in inspector.get_indexes("teaching_plans")},
            )

        columns, indexes, teaching_columns, teaching_indexes = await connection.run_sync(schema)

    await engine.dispose()

    assert "assignment_id" in columns
    assert "ix_question_attempts_assignment_id" in indexes
    assert {"classroom_id", "lesson_type", "learner_profile", "student_content", "package_json"} <= teaching_columns
    assert "ix_teaching_plans_classroom_id" in teaching_indexes
