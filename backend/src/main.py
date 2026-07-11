from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, Response
from sqlalchemy import text

from .config import ALLOWED_ORIGINS, IS_PRODUCTION, validate_runtime_config
from .db import models  # noqa: F401 - register ORM models
from .db.bootstrap import bootstrap_teacher
from .db.session import AsyncSessionLocal, Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_config()
    # Local SQLite stays one-command friendly. Production schema changes are
    # deliberately handled by Alembic before the application starts.
    if not IS_PRODUCTION:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    await bootstrap_teacher()
    yield
    await engine.dispose()


app = FastAPI(title="概率论与数理统计教学助手 API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .auth.handler import router as auth_router
from .question_bank.handler import router as question_bank_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(question_bank_router, prefix="/api", tags=["question_bank"])


@app.get("/health/live", tags=["health"])
async def liveness():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness():
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}


class SPAStaticFiles(StaticFiles):
    """Serve the React app for client-side routes."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return FileResponse(os.path.join(str(self.directory), "index.html"))
        if response.status_code == 404:
            return FileResponse(os.path.join(str(self.directory), "index.html"))
        return response


static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="static")
