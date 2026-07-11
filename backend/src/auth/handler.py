import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import APP_ENV, SECRET_KEY, TEACHER_REGISTRATION_CODE
from ..db.models import User
from ..db.session import get_db
from .security import hash_password, verify_password


router = APIRouter()
bearer = HTTPBearer()
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _dev_login_enabled() -> bool:
    return APP_ENV == "development" and _env_flag("DEV_LOGIN_ENABLED")


def create_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效") from exc
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


@router.get("/dev-login/status")
async def dev_login_status():
    return {"enabled": _dev_login_enabled()}


@router.post("/dev-login")
async def dev_login(db: AsyncSession = Depends(get_db)):
    if not _dev_login_enabled():
        raise HTTPException(status_code=404)
    username = os.environ.get("DEV_LOGIN_USER_ID", "local-teacher").strip() or "local-teacher"
    name = os.environ.get("DEV_LOGIN_NAME", "本地教师").strip() or "本地教师"
    role = os.environ.get("DEV_LOGIN_ROLE", "teacher").strip().lower()
    role = role if role in {"student", "teacher"} else "teacher"
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        user = User(username=username, name=name, role=role)
        db.add(user)
    else:
        user.name = name
        user.role = role
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user": _user_payload(user)}


@router.post("/register")
async def register(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    name = str(payload.get("name") or username).strip()
    role = str(payload.get("role") or "student").lower()
    teacher_code = str(payload.get("teacher_code") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少需要 8 位")
    if role not in {"student", "teacher"}:
        raise HTTPException(status_code=400, detail="身份必须是学生或教师")
    if role == "teacher" and (
        not TEACHER_REGISTRATION_CODE
        or not secrets.compare_digest(
            teacher_code.encode("utf-8"), TEACHER_REGISTRATION_CODE.encode("utf-8")
        )
    ):
        raise HTTPException(status_code=403, detail="教师邀请码无效或未配置")
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(username=username, name=name, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user": _user_payload(user)}


@router.post("/login")
async def login(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": create_token(user.id), "user": _user_payload(user)}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return _user_payload(user)


def _user_payload(user: User) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "avatar_url": user.avatar_url}
