import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Windows: uvicorn worker uses SelectorEventLoop by default, which does not support
# asyncio.create_subprocess_exec. Switch to ProactorEventLoop before anything starts.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Also replace the running loop if one already exists
    try:
        loop = asyncio.get_event_loop()
        if not isinstance(loop, asyncio.ProactorEventLoop):
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        pass

FEISHU_ENABLED = os.environ.get("FEISHU_ENABLED", "false").lower() == "true"
FEISHU_BOT_ENABLED = os.environ.get("FEISHU_BOT_ENABLED", "false").lower() == "true"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .db.session import engine, Base
from .db import models  # noqa: F401 — registers all ORM models with Base


async def _cleanup_orphaned_chat_messages():
    """Delete ReportChatMessage rows whose report no longer exists (SQLite ID reuse guard)."""
    from .db.session import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM report_chat_messages WHERE report_id NOT IN (SELECT id FROM reports)"
        ))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _cleanup_orphaned_chat_messages()

    # 重启后恢复上一进程未跑完的 ResearchTask（_running 只在内存，重启即丢）
    from .research_pipeline.scheduler import recover_orphaned_tasks, cleanup_stale_questions
    await recover_orphaned_tasks()

    if FEISHU_BOT_ENABLED:
        from .feishu_ws.client import start as start_feishu_ws
        from .bot.handler import on_message, on_card_action
        asyncio.create_task(start_feishu_ws(on_message, on_card_action))

    asyncio.create_task(cleanup_stale_questions())

    yield


app = FastAPI(title="概率论与数理统计教学助手 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth
from .auth.handler import router as auth_router
from .auth.feishu_oauth import router as feishu_oauth_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(feishu_oauth_router, prefix="/api/auth", tags=["auth"])

# Reports
from .reports.handler import router as reports_router
from .reports.chat_handler import router as report_chat_router

app.include_router(reports_router, prefix="/api", tags=["reports"])
app.include_router(report_chat_router, prefix="/api", tags=["report_chat"])

# Document review (admin)
from .document_review.handler import router as review_router

app.include_router(review_router, prefix="/api", tags=["review"])

# Pipeline / tasks / questions
from .research_pipeline.scheduler import router as pipeline_router

app.include_router(pipeline_router, prefix="/api", tags=["pipeline"])

# Web Ask (WebSocket interactive ask)
from .web_ask.handler import router as web_ask_router

app.include_router(web_ask_router, prefix="/api", tags=["web_ask"])

# Obsidian vault proxy
from .obsidian.handler import router as obsidian_router

app.include_router(obsidian_router, prefix="/api", tags=["obsidian"])

# Batch PDF ingest (admin)
from .ingest.handler import router as ingest_router

app.include_router(ingest_router, prefix="/api", tags=["ingest"])

# Admin: user management
from .admin.users_handler import router as admin_users_router

app.include_router(admin_users_router, prefix="/api", tags=["admin"])

# Probability & Mathematical Statistics question bank
from .question_bank.handler import router as question_bank_router

app.include_router(question_bank_router, prefix="/api", tags=["question_bank"])

# Serve built frontend (Vite output → backend/static/).
# SPA fallback: client-side routes (/sessions, /review, /reports/:id) must return
# index.html on hard-refresh / direct navigation instead of 404. The /api/* routers
# are registered above this mount, so they always take precedence.
class _SPAStaticFiles(StaticFiles):
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


_static = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static):
    app.mount("/", _SPAStaticFiles(directory=_static, html=True), name="static")
