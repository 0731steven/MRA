"""Small, additive schema repairs for unversioned local SQLite databases."""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection


async def ensure_local_sqlite_compatibility(connection: AsyncConnection) -> None:
    """Bring an existing development database forward without replacing data.

    Local development historically relied on ``metadata.create_all()``. That
    creates missing tables but cannot add columns to tables that already exist.
    Keep the repair deliberately narrow: production databases continue to use
    Alembic, while old local SQLite files receive only safe, additive changes.
    """

    if connection.dialect.name != "sqlite":
        return

    def table_columns(sync_connection, table_name: str) -> set[str]:
        inspector = inspect(sync_connection)
        if table_name not in inspector.get_table_names():
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    columns = await connection.run_sync(table_columns, "question_attempts")
    if not columns:
        return

    if "assignment_id" not in columns:
        await connection.execute(
            text(
                "ALTER TABLE question_attempts "
                "ADD COLUMN assignment_id INTEGER "
                "REFERENCES learning_assignments(id) ON DELETE SET NULL"
            )
        )

    await connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_question_attempts_assignment_id "
            "ON question_attempts (assignment_id)"
        )
    )

    teaching_columns = await connection.run_sync(table_columns, "teaching_plans")
    if not teaching_columns:
        return
    additions = {
        "classroom_id": "INTEGER REFERENCES classrooms(id) ON DELETE SET NULL",
        "lesson_type": "VARCHAR(24) NOT NULL DEFAULT 'concept'",
        "learner_profile": "VARCHAR(24) NOT NULL DEFAULT 'mixed'",
        "student_content": "TEXT",
        "package_json": "TEXT",
    }
    for column_name, definition in additions.items():
        if column_name not in teaching_columns:
            await connection.execute(text(f"ALTER TABLE teaching_plans ADD COLUMN {column_name} {definition}"))
    await connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_teaching_plans_classroom_id "
            "ON teaching_plans (classroom_id)"
        )
    )
