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
            question_text = str(row.get("question") or "").lower()
            answer_text = f"{row.get('answer') or ''} {row.get('explanation') or ''}".lower()
            keypoint_text = " ".join(row.get("keypoint") or []).lower()
            metadata_text = f"{row.get('qtype') or ''} {row.get('hard_level') or ''}".lower()
            value = 0.0
            if q.upper() == str(row.get("ID") or "").upper():
                value += 1000
            if q in question_text:
                value += 120
            if q in keypoint_text:
                value += 160
            if q in answer_text:
                value += 20
            question_overlap = len(q_tokens & _tokens(question_text))
            keypoint_overlap = len(q_tokens & _tokens(keypoint_text))
            answer_overlap = len(q_tokens & _tokens(answer_text))
            metadata_overlap = len(q_tokens & _tokens(metadata_text))
            value += question_overlap * 8 + keypoint_overlap * 14 + answer_overlap * 1.5 + metadata_overlap * 4
            if q_tokens:
                value += (question_overlap + keypoint_overlap) / len(q_tokens) * 25
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

    # Natural-language questions contain a lot of instructional wording such as
    # “如何判断一道题该用……”.  Searching the whole sentence can dilute the actual
    # mathematical term.  Resolve explicit question-bank keypoints first, then
    # use the full sentence for supplementary semantic/lexical matches.
    normalized_message = re.sub(r"\s+", "", message.lower())
    known_keypoints = {
        str(keypoint)
        for row in load_questions()
        for keypoint in (row.get("keypoint") or [])
        if keypoint
    }
    raw_keypoints = [
        keypoint for keypoint in known_keypoints if keypoint.lower() in normalized_message
    ]
    # Prefer the most specific phrase when bank labels overlap.  Without this,
    # “样本空间” also matched the broad “样本” label and recommended unrelated
    # mathematical-statistics exercises.
    matched_keypoints = sorted(
        (
            keypoint
            for keypoint in raw_keypoints
            if not any(
                keypoint != other and keypoint.lower() in other.lower()
                for other in raw_keypoints
            )
        ),
        key=lambda keypoint: (normalized_message.index(keypoint.lower()), -len(keypoint)),
    )
    difficulty = ""
    if any(word in normalized_message for word in ("简单", "基础", "入门", "容易", "易题")):
        difficulty = "易"
    elif any(word in normalized_message for word in ("困难", "难题", "提高", "拔高", "挑战")):
        difficulty = "难"
    elif any(word in normalized_message for word in ("中等", "适中")):
        difficulty = "中"
    # Pull from all explicitly named keypoints in rounds.  Filling the result
    # from the first keypoint alone made comparison questions such as
    # “条件概率和全概率公式有什么区别” one-sided.  Bank order is pedagogically
    # friendlier than lexical scoring here: introductory IDs precede later,
    # specialised exercises (for example a non-central Gamma proof).
    keypoint_groups: list[list[dict[str, Any]]] = []
    for keypoint in matched_keypoints:
        matches, _ = search_questions(
            "",
            keypoint=keypoint,
            difficulty=difficulty,
            page_size=max(limit * 2, 10),
        )
        keypoint_groups.append(matches)
    group_indexes = [0] * len(keypoint_groups)
    while keypoint_groups and len(chosen) < limit:
        added = False
        for index, matches in enumerate(keypoint_groups):
            while group_indexes[index] < len(matches) and matches[group_indexes[index]]["ID"] in seen:
                # An exercise can cover multiple named keypoints.  Skip the
                # duplicate but keep advancing this group's cursor.
                group_indexes[index] += 1
            if group_indexes[index] < len(matches):
                row = matches[group_indexes[index]]
                group_indexes[index] += 1
                chosen.append(row)
                seen.add(row["ID"])
                added = True
                if len(chosen) >= limit:
                    return chosen[:limit]
        if not added:
            break

    matches, _ = search_questions(message, difficulty=difficulty, page_size=max(limit * 2, 10))
    for row in matches:
        if row["ID"] not in seen:
            chosen.append(row)
            seen.add(row["ID"])
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def is_contextual_follow_up(message: str) -> bool:
    """Return whether a message likely refers to the preceding sourced question."""
    normalized = re.sub(r"\s+", "", message.lower())
    if re.search(r"P\d{6}", normalized.upper()):
        return False
    known_keypoints = {
        str(keypoint).lower()
        for row in load_questions()
        for keypoint in (row.get("keypoint") or [])
        if keypoint
    }
    names_topic = any(keypoint in normalized for keypoint in known_keypoints)
    referential_markers = (
        "这道题", "这题", "上题", "上一题", "刚才", "上述", "这里", "这一步",
        "再讲", "没懂", "换种", "继续", "然后呢", "我的思路",
    )
    if any(marker in normalized for marker in referential_markers):
        return True
    # “为什么/怎么算” can introduce a new, explicitly named topic.  Only treat
    # these generic forms as a continuation when no bank keypoint is named.
    generic_markers = ("为什么", "怎么算", "哪里错")
    if any(marker in normalized for marker in generic_markers):
        return not names_topic
    # Very short questions without a named bank keypoint are usually continuations.
    return len(normalized) <= 12 and not names_topic


def requested_recommendation_count(message: str, default: int = 6, maximum: int = 8) -> int:
    """Extract an explicit exercise count such as “3道” or “三道题”."""
    chinese_numbers = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    match = re.search(
        r"(?<!\d)(\d{1,3}|[一二两三四五六七八九十])\s*(?:道\s*题?|个\s*(?:题|练习)|题)",
        message,
    )
    if not match:
        return max(1, min(default, maximum))
    token = match.group(1)
    value = int(token) if token.isdigit() else chinese_numbers[token]
    return max(1, min(value, maximum))
