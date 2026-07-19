"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///./teaching_assistant.db"
).strip()
_configured_secret = os.environ.get("SECRET_KEY", "dev-secret-change-me-please")
# Development may inherit an old short local secret. Derive a stable 32-byte
# value to avoid weak-key warnings without weakening production validation.
SECRET_KEY = (
    _configured_secret
    if IS_PRODUCTION or len(_configured_secret) >= 32
    else hashlib.sha256(f"mra-development-only:{_configured_secret}".encode()).hexdigest()
)
TEACHER_REGISTRATION_CODE = os.environ.get("TEACHER_REGISTRATION_CODE", "").strip()


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


ALLOWED_ORIGINS = _csv_env(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173" if not IS_PRODUCTION else "",
)


def validate_runtime_config() -> None:
    """Fail fast when production is started with unsafe configuration."""

    if not IS_PRODUCTION:
        return
    if len(SECRET_KEY) < 32 or SECRET_KEY in {
        "dev-secret-change-me-please",
        "replace-with-at-least-32-random-characters",
    }:
        raise RuntimeError("生产环境必须配置至少 32 个字符的 SECRET_KEY")
    if not DATABASE_URL.startswith("postgresql+asyncpg://"):
        raise RuntimeError("生产环境必须使用 PostgreSQL DATABASE_URL")
    if "*" in ALLOWED_ORIGINS:
        raise RuntimeError("生产环境的 ALLOWED_ORIGINS 不能使用通配符 *")
