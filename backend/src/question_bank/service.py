from __future__ import annotations

import json
import os
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_BANK_PATH = Path(__file__).resolve().parents[2] / "data" / "probability_questions.jsonl"
BANK_PATH = Path(os.environ.get("QUESTION_BANK_PATH", str(DEFAULT_BANK_PATH))).expanduser()


@lru_cache(maxsize=1)
def load_questions() -> list[dict[str, Any]]:
    if not BANK_PATH.exists():
        raise RuntimeError(f"题库文件不存在：{BANK_PATH}")
    rows: list[dict[str, Any]] = []
    with BANK_PATH.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"题库第 {line_no} 行 JSON 格式错误") from exc
            row["id"] = row.get("ID")
            rows.append(row)
    return rows


def _tokens(text: str) -> set[str]:
    text = text.lower().strip()
    words = set(re.findall(r"[a-z0-9_]+", text))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    if len(chinese) == 1:
        words.add(chinese)
    else:
        words.update(chinese[i : i + 2] for i in range(len(chinese) - 1))
    return {token for token in words if token}


def _search_text(row: dict[str, Any]) -> str:
    return " ".join(
        [
            str(row.get("ID") or ""),
            str(row.get("question") or ""),
            str(row.get("answer") or ""),
            " ".join(row.get("keypoint") or []),
            str(row.get("qtype") or ""),
            str(row.get("hard_level") or ""),
        ]
    ).lower()


def search_questions(
    query: str = "",
    *,
    qtype: str = "",
    difficulty: str = "",
    keypoint: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    rows = load_questions()
    filtered = [
        row
        for row in rows
        if (not qtype or row.get("qtype") == qtype)
        and (not difficulty or row.get("hard_level") == difficulty)
        and (not keypoint or keypoint in (row.get("keypoint") or []))
    ]
    if query.strip():
        q = query.lower().strip()
        q_tokens = _tokens(q)

        def score(row: dict[str, Any]) -> float:
            text = _search_text(row)
            value = 0.0
            if q.upper() == str(row.get("ID") or "").upper():
                value += 1000
            if q in text:
                value += 80
            row_tokens = _tokens(text)
            value += len(q_tokens & row_tokens) * 3
            for kp in row.get("keypoint") or []:
                if q in str(kp).lower():
                    value += 30
            return value

        min_overlap = max(1, math.ceil(len(q_tokens) * 0.45))
        scored = []
        for row in filtered:
            text = _search_text(row)
            overlap = len(q_tokens & _tokens(text))
            if q in text or q.upper() == str(row.get("ID") or "").upper() or overlap >= min_overlap:
                scored.append((score(row), row))
        filtered = [row for _, row in sorted(scored, key=lambda x: x[0], reverse=True)]
    total = len(filtered)
    start = (page - 1) * page_size
    return filtered[start : start + page_size], total


def get_question(question_id: str) -> dict[str, Any] | None:
    wanted = question_id.upper()
    return next((row for row in load_questions() if str(row.get("ID", "")).upper() == wanted), None)


def compact_question(row: dict[str, Any], include_answer: bool = False) -> dict[str, Any]:
    fields = ["ID", "qtype", "question", "choices", "keypoint", "hard_level", "subject"]
    if include_answer:
        fields.extend(["answer", "explanation"])
    return {field: row.get(field) for field in fields}


def bank_stats() -> dict[str, Any]:
    rows = load_questions()

    def counts(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            value = str(row.get(field) or "未标注")
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))

    kp_counts: dict[str, int] = {}
    for row in rows:
        for kp in row.get("keypoint") or []:
            kp_counts[kp] = kp_counts.get(kp, 0) + 1
    return {
        "total": len(rows),
        "qtypes": counts("qtype"),
        "difficulties": counts("hard_level"),
        "keypoints": dict(sorted(kp_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def retrieve_context(message: str, question_ids: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    embedded_ids = re.findall(r"P\d{6}", message.upper())
    for question_id in [*(question_ids or []), *embedded_ids]:
        row = get_question(question_id)
        if row and row["ID"] not in seen:
            chosen.append(row)
            seen.add(row["ID"])
    matches, _ = search_questions(message, page_size=max(limit * 2, 10))
    for row in matches:
        if row["ID"] not in seen:
            chosen.append(row)
            seen.add(row["ID"])
        if len(chosen) >= limit:
            break
    return chosen[:limit]
