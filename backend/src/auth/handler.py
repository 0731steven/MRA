import hashlib
import os
import secrets
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, HTTPBasic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_db
from ..db.models import User


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt, h = stored.split("$", 1)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex() == h

router = APIRouter()
bearer = HTTPBearer()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7

APP_ENV = os.environ.get("APP_ENV", "development")
ADMIN_FEISHU_IDS: set[str] = set(filter(None, os.environ.get("ADMIN_FEISHU_IDS", "").split(",")))


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _dev_login_enabled() -> bool:
    """Developer login must be explicitly enabled and is never available in production."""
    return APP_ENV == "development" and _env_flag("DEV_LOGIN_ENABLED")


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user_query(
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Auth via ?token= query param — for iframe/img src that can't set headers."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


async def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher only")
    return user


@router.get("/dev-login/status")
async def dev_login_status():
    return {"enabled": _dev_login_enabled()}


@router.post("/dev-login")
async def dev_login(
    db: AsyncSession = Depends(get_db),
):
    if not _dev_login_enabled():
        raise HTTPException(status_code=404)

    feishu_user_id = os.environ.get("DEV_LOGIN_USER_ID", "local-developer").strip() or "local-developer"
    name = os.environ.get("DEV_LOGIN_NAME", "本地开发者").strip() or "本地开发者"
    configured_role = os.environ.get("DEV_LOGIN_ROLE", "admin").strip().lower()
    role = configured_role if configured_role in {"student", "teacher", "user", "admin"} else "teacher"

    result = await db.execute(select(User).where(User.feishu_user_id == feishu_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(feishu_user_id=feishu_user_id, name=name, role=role)
        db.add(user)
    else:
        # Keep the dedicated local account aligned with the current dev settings.
        user.name = name
        user.role = role
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user": {"id": user.id, "name": user.name, "role": user.role}}


@router.post("/register")
async def register(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    name = payload.get("name") or username
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="password too short")

    result = await db.execute(select(User).where(User.feishu_user_id == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="username already exists")

    requested_role = str(payload.get("role") or "student").lower()
    role = "admin" if username in ADMIN_FEISHU_IDS else requested_role
    if role not in {"student", "teacher"} and role != "admin":
        raise HTTPException(status_code=400, detail="role must be student or teacher")
    user = User(
        feishu_user_id=username,
        name=name,
        password_hash=_hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user": {"id": user.id, "name": user.name, "role": user.role}}


@router.post("/login")
async def login(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")

    result = await db.execute(select(User).where(User.feishu_user_id == username))
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash or not _verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")

    return {"token": create_token(user.id), "user": {"id": user.id, "name": user.name, "role": user.role}}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "role": user.role, "avatar_url": user.avatar_url}
