"""Entry point: uvicorn src.main:app"""
import asyncio
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
os.chdir(BACKEND_DIR)
load_dotenv(BACKEND_DIR / ".env")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APP_PORT", "8101")),
        reload=False,
    )
