import os
import httpx
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_db
from ..db.models import User
from .handler import create_token, ADMIN_FEISHU_IDS

router = APIRouter()

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_REDIRECT_URI = os.environ.get("FEISHU_REDIRECT_URI", "")
FEISHU_ENABLED = os.environ.get("FEISHU_ENABLED", "false").lower() == "true"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")


@router.get("/feishu/login")
async def feishu_login():
    if not FEISHU_ENABLED:
        raise HTTPException(status_code=404)
    url = (
        "https://open.feishu.cn/open-apis/authen/v1/authorize"
        f"?app_id={FEISHU_APP_ID}"
        f"&redirect_uri={quote(FEISHU_REDIRECT_URI, safe='')}"
        "&scope=contact:user.base:readonly"
    )
    return RedirectResponse(url)


@router.get("/feishu/callback")
async def feishu_callback(code: str, db: AsyncSession = Depends(get_db)):
    if not FEISHU_ENABLED:
        raise HTTPException(status_code=404)

    async with httpx.AsyncClient() as client:
        app_resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        )
        app_data = app_resp.json()
        app_access_token = app_data.get("app_access_token", "")
        if not app_access_token:
            raise HTTPException(status_code=502, detail=f"feishu app_token failed: {app_data}")

        user_token_resp = await client.post(
            "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
            headers={"Authorization": f"Bearer {app_access_token}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        user_token_data = user_token_resp.json()
        user_access_token = user_token_data.get("data", {}).get("access_token", "")
        if not user_access_token:
            raise HTTPException(status_code=502, detail=f"feishu user_token failed: {user_token_data}")

        info_resp = await client.get(
            "https://open.feishu.cn/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        info = info_resp.json().get("data", {})

    feishu_user_id = info.get("open_id") or info.get("user_id", "")
    name = info.get("name", "Unknown")
    avatar_url = info.get("avatar_url")
    role = "admin" if feishu_user_id in ADMIN_FEISHU_IDS else "user"

    result = await db.execute(select(User).where(User.feishu_user_id == feishu_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(feishu_user_id=feishu_user_id, name=name, avatar_url=avatar_url, role=role)
        db.add(user)
    else:
        user.name = name
        user.avatar_url = avatar_url
        user.role = role
    await db.commit()
    await db.refresh(user)

    token = create_token(user.id)
    return RedirectResponse(f"{FRONTEND_URL}/login?token={token}")


@router.post("/feishu/exchange")
async def feishu_exchange(payload: dict, db: AsyncSession = Depends(get_db)):
    if not FEISHU_ENABLED:
        raise HTTPException(status_code=404)
    code = payload.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    async with httpx.AsyncClient() as client:
        # Step 1: get app access token
        app_resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        )
        app_data = app_resp.json()
        app_access_token = app_data.get("app_access_token", "")
        if not app_access_token:
            raise HTTPException(status_code=502, detail=f"feishu app_token failed: {app_data}")

        # Step 2: exchange code for user access token
        user_token_resp = await client.post(
            "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
            headers={"Authorization": f"Bearer {app_access_token}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        user_token_data = user_token_resp.json()
        user_access_token = user_token_data.get("data", {}).get("access_token", "")
        if not user_access_token:
            raise HTTPException(status_code=502, detail=f"feishu user_token failed: {user_token_data}")

        # Step 3: get user info
        info_resp = await client.get(
            "https://open.feishu.cn/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        info = info_resp.json().get("data", {})

    feishu_user_id = info.get("open_id") or info.get("user_id", "")
    name = info.get("name", "Unknown")
    avatar_url = info.get("avatar_url")
    role = "admin" if feishu_user_id in ADMIN_FEISHU_IDS else "user"

    result = await db.execute(select(User).where(User.feishu_user_id == feishu_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(feishu_user_id=feishu_user_id, name=name, avatar_url=avatar_url, role=role)
        db.add(user)
    else:
        user.name = name
        user.avatar_url = avatar_url
        user.role = role
    await db.commit()
    await db.refresh(user)

    return {"token": create_token(user.id)}
