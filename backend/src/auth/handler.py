import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import APP_ENV, IS_PRODUCTION, SECRET_KEY, TEACHER_REGISTRATION_CODE
from ..db.models import User
from ..db.session import get_db
from .security import hash_password, verify_password


router = APIRouter()
bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7
SESSION_COOKIE = "mra_session"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    role: str = Field(default="student", max_length=16)
    teacher_code: str = Field(default="", max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _dev_login_enabled() -> bool:
    return APP_ENV == "development" and _env_flag("DEV_LOGIN_ENABLED")


def _dev_login_role() -> str:
    role = os.environ.get("DEV_LOGIN_ROLE", "teacher").strip().lower()
    return role if role in {"student", "teacher"} else "teacher"


def create_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else session_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效") from exc
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


@router.get("/dev-login/status")
async def dev_login_status():
    enabled = _dev_login_enabled()
    return {"enabled": enabled, "role": _dev_login_role() if enabled else None}


@router.post("/dev-login")
async def dev_login(response: Response, db: AsyncSession = Depends(get_db)):
    if not _dev_login_enabled():
        raise HTTPException(status_code=404)
    username = os.environ.get("DEV_LOGIN_USER_ID", "local-teacher").strip() or "local-teacher"
    name = os.environ.get("DEV_LOGIN_NAME", "本地教师").strip() or "本地教师"
    role = _dev_login_role()
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    creating = user is None
    if user is None:
        user = User(username=username, name=name, role=role)
        db.add(user)
    else:
        user.name = name
        user.role = role
    try:
        await db.commit()
    except IntegrityError:
        if not creating:
            raise
        # Two local browser sessions can click the development shortcut at the
        # same time.  The first insert wins; reuse that user instead of turning
        # the harmless race into a 500 response.
        await db.rollback()
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None:
            raise
        user.name = name
        user.role = role
        await db.commit()
    await db.refresh(user)
    token = create_token(user.id)
    _set_session_cookie(response, token)
    return {"user": _user_payload(user)}


@router.post("/register")
async def register(payload: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    username = payload.username.strip()
    password = payload.password
    name = (payload.name or "").strip() or username
    role = payload.role.strip().lower()
    teacher_code = payload.teacher_code
    if not username:
        raise HTTPException(status_code=400, detail="请输入用户名")
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
    token = create_token(user.id)
    _set_session_cookie(response, token)
    return {"user": _user_payload(user)}


@router.post("/login")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    username = payload.username.strip()
    password = payload.password
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user.id)
    _set_session_cookie(response, token)
    return {"user": _user_payload(user)}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=IS_PRODUCTION,
        httponly=True,
        samesite="lax",
    )
    return {"logged_out": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return _user_payload(user)


def _user_payload(user: User) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "avatar_url": user.avatar_url}
