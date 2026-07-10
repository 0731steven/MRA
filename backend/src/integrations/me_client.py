"""Read-only Market Engine client.

MRA never writes to ME. In local development ``ME_API_MODE=mock`` keeps the
pipeline runnable without access to Southchip's intranet.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from typing import Any

@dataclass
class MEDataBlock:
    endpoint: str
    title: str
    content: str
    evidence_slot: str
    source_url: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ENDPOINTS: dict[str, list[tuple[str, str]]] = {
    "competitive": [
        ("/api/v1/competitive-dynamics/summary", "E1"),
        ("/api/v1/competitive-dynamics/new-products", "E2"),
        ("/api/v1/competitive-dynamics/financials", "E3"),
        ("/api/v1/competitive-dynamics/recruitment", "E4"),
        ("/api/v1/competitive-dynamics/patents", "E4"),
        ("/api/v1/competitive-dynamics/signals", "E4"),
        ("/api/v1/nas-kb/search", "E1"),
    ],
    "product": [
        ("/api/v1/competitive-dynamics/new-products", "E2"),
        ("/api/v1/competitive-dynamics/signals", "E4"),
        ("/api/v1/signals", "E4"),
        ("/api/v1/nas-kb/search", "E1"),
    ],
    "market": [
        ("/api/v1/signals", "E4"),
        ("/api/v1/intel/weekly-batches", "E1"),
        ("/api/v1/intel/daily-reports", "E1"),
        ("/api/v1/nas-kb/search", "E1"),
        ("/api/v1/raw-signals/private", "E4"),
    ],
    "technology": [
        ("/api/v1/signals", "E4"),
        ("/api/v1/competitive-dynamics/patents", "E4"),
        ("/api/v1/nas-kb/search", "E1"),
    ],
}


def _flatten(endpoint: str, slot: str, payload: Any) -> list[MEDataBlock]:
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "signals", "rows"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []
    blocks: list[MEDataBlock] = []
    for i, item in enumerate(payload[:50]):
        if not isinstance(item, dict):
            item = {"value": item}
        title = str(item.get("title") or item.get("name") or item.get("company") or f"ME 数据 {i + 1}")
        content = "\n".join(f"{k}: {v}" for k, v in item.items() if v not in (None, "", [], {}))
        blocks.append(MEDataBlock(
            endpoint=endpoint,
            title=title,
            content=content,
            evidence_slot=slot,
            source_url=str(item.get("url") or item.get("source_url") or ""),
            published_at=str(item.get("published_at") or item.get("signal_date") or item.get("date") or ""),
        ))
    return blocks


def _trim_blocks(blocks: list[dict], query: str, limit: int = 30) -> list[dict]:
    """Keep endpoint diversity, then fill remaining slots by token overlap."""
    if len(blocks) <= limit:
        return blocks
    terms = {t.lower() for t in query.split() if t.strip()}
    grouped: dict[str, list[dict]] = {}
    for block in blocks:
        grouped.setdefault(str(block.get("endpoint", "")), []).append(block)
    selected: list[dict] = []
    remaining: list[dict] = []
    for values in grouped.values():
        ranked = sorted(values, key=lambda b: sum(term in f"{b.get('title', '')} {b.get('content', '')}".lower() for term in terms), reverse=True)
        selected.extend(ranked[:3])
        remaining.extend(ranked[3:])
    if len(selected) > limit:
        return selected[:limit]
    remaining.sort(key=lambda b: sum(term in f"{b.get('title', '')} {b.get('content', '')}".lower() for term in terms), reverse=True)
    return selected + remaining[:limit - len(selected)]


async def fetch_report_data(report_type: str, params: dict[str, Any], keywords: list[str]) -> tuple[list[dict], dict]:
    mode = os.environ.get("ME_API_MODE", "mock").lower()
    endpoints = ENDPOINTS.get(report_type, ENDPOINTS["market"])
    stats: dict[str, Any] = {"mode": mode, "endpoints": {}, "total": 0}
    if mode != "real":
        stats["warning"] = "Market Engine 使用 Mock 模式，未读取南芯内网数据"
        return [], stats

    base = os.environ.get("ME_API_BASE_URL", "").rstrip("/")
    if not base:
        stats["warning"] = "ME_API_BASE_URL 未配置"
        return [], stats
    import httpx
    headers = {}
    if os.environ.get("ME_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['ME_API_KEY']}"
    query = " ".join(keywords)
    company = params.get("target_company") or (params.get("competitors") or [""])[0]

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers=headers) as client:
        async def one(path: str, slot: str) -> tuple[str, list[MEDataBlock], str | None]:
            try:
                response = await client.get(base + path, params={"q": query, "company": company, "limit": 30})
                response.raise_for_status()
                return path, _flatten(path, slot, response.json()), None
            except Exception as exc:
                return path, [], f"{type(exc).__name__}: {exc}"

        results = await asyncio.gather(*(one(path, slot) for path, slot in endpoints))

    blocks: list[dict] = []
    for path, values, error in results:
        stats["endpoints"][path] = {"count": len(values), "error": error}
        blocks.extend(v.to_dict() for v in values)
    stats["total_raw"] = len(blocks)
    blocks = _trim_blocks(blocks, query)
    stats["total"] = len(blocks)
    return blocks, stats
