"""Optional first teacher account creation for a fresh installation."""

import os

from sqlalchemy import select

from ..auth.security import hash_password
from ..config import IS_PRODUCTION
from .models import User
from .session import AsyncSessionLocal


async def bootstrap_teacher() -> None:
    username = os.environ.get("BOOTSTRAP_TEACHER_USERNAME", "").strip()
    password = os.environ.get("BOOTSTRAP_TEACHER_PASSWORD", "")
    name = os.environ.get("BOOTSTRAP_TEACHER_NAME", "初始教师").strip() or "初始教师"

    if not username and not password:
        return
    if not username or not password:
        raise RuntimeError("初始教师账号必须同时配置用户名和密码")
    if len(password) < (12 if IS_PRODUCTION else 8):
        raise RuntimeError("初始教师密码长度不足")

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    username=username,
                    name=name,
                    password_hash=hash_password(password),
                    role="teacher",
                )
            )
            await session.commit()
