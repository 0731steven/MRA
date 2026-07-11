from sqlalchemy import text

from src.db.session import engine


async def test_database_connection():
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT 1")) == 1
