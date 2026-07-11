"""Tests for the teaching assistant SPA fallback."""
from __future__ import annotations

import os

import httpx
import pytest
from httpx import ASGITransport

from src.main import app

# The mount only exists if backend/static was built. Skip cleanly if absent.
_STATIC = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
pytestmark = pytest.mark.skipif(
    not os.path.isfile(_STATIC), reason="frontend not built (backend/static missing)"
)


async def _get(path: str) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_client_route_serves_index_html() -> None:
    """An unknown non-API path returns 200 + the SPA shell, not 404."""
    resp = await _get("/tutor")
    assert resp.status_code == 200
    assert "<div id=\"root\">" in resp.text or "<!doctype html" in resp.text.lower()


async def test_root_serves_index_html() -> None:
    resp = await _get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


async def test_api_route_not_shadowed_by_fallback() -> None:
    """/api/* must hit the API (401 without a token), never the SPA fallback."""
    resp = await _get("/api/auth/me")
    assert resp.status_code in (401, 403)
    assert "<!doctype html" not in resp.text.lower()
