import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, Response

from .db import models  # noqa: F401 - register ORM models
from .db.session import Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="概率论与数理统计教学助手 API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .auth.handler import router as auth_router
from .question_bank.handler import router as question_bank_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(question_bank_router, prefix="/api", tags=["question_bank"])


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
