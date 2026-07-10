"""L0/L1/L2 company library retrieval with forced evidence quotas."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .bm25 import score
from .chunker import chunk_markdown


COMPANY_LIB = Path(os.environ.get("COMPANY_LIB_PATH", str(Path.home() / "company_lib"))).expanduser()
SKIP_DIRS = {"generated", "staging", ".git", "node_modules"}


def _kind(path: Path) -> str:
    p = path.as_posix().lower()
    if "/fact_cards/" in f"/{p}" or "/market_cards/" in f"/{p}" or "/tech_cards/" in f"/{p}" or "/company_info/" in f"/{p}":
        return "l1"
    if "/competitive/" in f"/{p}" and "financial" in p:
        return "financial"
    if "/bom/" in f"/{p}":
        return "bom"
    return "l0"


def _iter_docs() -> list[Path]:
    if not COMPANY_LIB.exists():
        return []
    return [p for p in COMPANY_LIB.rglob("*.md") if not any(part in SKIP_DIRS for part in p.relative_to(COMPANY_LIB).parts)]


def retrieve_candidates(query: str, report_type: str, params: dict[str, Any] | None = None) -> list[dict]:
    params = params or {}
    files = _iter_docs()
    if not files:
        return []
    docs: list[tuple[Path, str]] = []
    for path in files:
        try:
            docs.append((path, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    scores = score(query, [f"{p.name}\n{text[:10000]}" for p, text in docs])
    candidates: list[dict] = []
    query_terms = [t.lower() for t in query.split() if len(t.strip()) >= 2]
    for (path, text), value in zip(docs, scores):
        kind = _kind(path.relative_to(COMPANY_LIB))
        boost = 3.0 if kind == "l1" else 0.0
        haystack = f"{path.name} {text[:3000]}".lower()
        target_match = any(term in haystack for term in query_terms)
        if report_type == "competitive" and kind == "financial" and target_match:
            boost += 4.0
        if report_type in {"market", "product"} and kind == "bom" and target_match:
            boost += 2.0
        if value > 0 or boost > 0:
            candidates.append({
                "path": str(path),
                "relative_path": str(path.relative_to(COMPANY_LIB)),
                "title": path.stem,
                "kind": kind,
                "score": round(value + boost, 4),
                "content": text,
            })
    candidates.sort(key=lambda x: (x["kind"] == "l1", x["score"]), reverse=True)
    return candidates


def build_context_blocks(candidates: list[dict], query: str, *, char_budget: int | None = None) -> list[dict]:
    budget = char_budget or int(os.environ.get("MRA_KB_CHAR_BUDGET", "120000"))
    raw: list[dict] = []
    for doc in candidates:
        chunk_size = 2500 if "market_report" in doc.get("relative_path", "") else 1600
        chunks = chunk_markdown(doc.get("content", ""), size=chunk_size)
        chunk_scores = score(query, chunks)
        for index, (chunk, value) in enumerate(zip(chunks, chunk_scores)):
            raw.append({
                "source_type": "kb_l1" if doc.get("kind") == "l1" else "kb",
                "source_id": f"{doc.get('relative_path')}#{index}",
                "title": doc.get("title", ""),
                "path": doc.get("relative_path", ""),
                "content": chunk,
                "score": value + float(doc.get("score", 0)) * 0.15,
            })
    priority = {"kb_l1": 0, "kb": 2}
    raw.sort(key=lambda b: (priority.get(b["source_type"], 9), -b["score"]))
    selected: list[dict] = []
    used = 0
    seen: set[str] = set()
    for block in raw:
        signature = block["content"][:240]
        if signature in seen:
            continue
        size = len(block["content"])
        if used + size > budget:
            continue
        seen.add(signature)
        selected.append(block)
        used += size
    return selected


def load_index() -> dict:
    path = COMPANY_LIB / "_index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
