from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..question_bank.analytics import PREREQUISITES, build_learning_profile


GROUP_META = {
    "needs_diagnostic": {
        "label": "证据积累组",
        "strategy": "先完成一组短诊断，避免在证据不足时提前分层。",
    },
    "prerequisite_gap": {
        "label": "前置回补组",
        "strategy": "先回补薄弱的前置知识，再返回当前目标进行验证。",
    },
    "hint_dependent": {
        "label": "去提示练习组",
        "strategy": "使用同构题逐步减少提示，并以一道无提示题检查独立完成能力。",
    },
    "needs_foundation": {
        "label": "概念巩固组",
        "strategy": "从基础题到中等题递进，要求解释公式使用条件。",
    },
    "transfer_ready": {
        "label": "迁移挑战组",
        "strategy": "使用不同情境的中高难度题验证是否能稳定迁移。",
    },
}


def _student_group(profile: dict[str, Any], student_attempts: list[dict[str, Any]]) -> tuple[str, str]:
    summary = profile["summary"]
    evidence = profile["evidence"]
    focus = str(summary["next_focus"])
    if evidence["questions"] < 2:
        return "needs_diagnostic", focus

    mastery_by_name = {item["name"]: item for item in profile["mastery"]}
    focus_item = mastery_by_name.get(focus)
    weak_prerequisites = [
        name
        for name in PREREQUISITES.get(focus, [])
        if name not in mastery_by_name or mastery_by_name[name]["score"] < 65
    ]
    if focus_item and focus_item["status"] == "at_risk" and weak_prerequisites:
        return "prerequisite_gap", weak_prerequisites[0]

    hints = sum(int(item.get("hint_count") or 0) for item in student_attempts)
    if hints >= 2 and hints / max(len(student_attempts), 1) >= 0.5:
        return "hint_dependent", focus
    if summary["overall_mastery"] >= 75 and summary["risk_keypoints"] == 0 and summary["evidence_level"] != "low":
        return "transfer_ready", focus
    return "needs_foundation", focus


def build_classroom_radar(
    rows: list[dict[str, Any]],
    students: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    attempts_by_student: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_student[int(attempt["user_id"])].append(attempt)

    student_rows: list[dict[str, Any]] = []
    concept_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    independent_transfer_students: set[int] = set()

    for student in students:
        student_id = int(student["id"])
        evidence = attempts_by_student.get(student_id, [])
        profile = build_learning_profile(rows, evidence)
        group_key, focus = _student_group(profile, evidence)
        grouped[(group_key, focus)].append(student_id)
        errors = Counter(str(item.get("error_type")) for item in evidence if item.get("error_type"))
        for mastery in profile["mastery"]:
            concept_evidence[mastery["name"]].append(mastery)
        if any(
            item.get("assignment_kind") in {"intervention", "retest"}
            and item.get("verdict") == "correct"
            and int(item.get("hint_count") or 0) == 0
            for item in evidence
        ):
            independent_transfer_students.add(student_id)
        student_rows.append(
            {
                "id": student_id,
                "name": student["name"],
                "overall_mastery": profile["summary"]["overall_mastery"],
                "evidence_level": profile["summary"]["evidence_level"],
                "attempts": profile["evidence"]["attempts"],
                "questions": profile["evidence"]["questions"],
                "risk_keypoints": profile["summary"]["risk_keypoints"],
                "next_focus": profile["summary"]["next_focus"],
                "top_error": errors.most_common(1)[0][0] if errors else None,
                "group_key": group_key,
                "group_label": GROUP_META[group_key]["label"],
                "group_focus": focus,
                "independent_transfer": student_id in independent_transfer_students,
            }
        )

    keypoints: list[dict[str, Any]] = []
    for name, items in concept_evidence.items():
        weights = [max(int(item["confidence"]), 20) for item in items]
        total_weight = sum(weights) or 1
        errors = Counter(str(item.get("top_error")) for item in items if item.get("top_error"))
        keypoints.append(
            {
                "name": name,
                "mastery": round(sum(item["score"] * weight for item, weight in zip(items, weights)) / total_weight),
                "confidence": round(sum(item["confidence"] for item in items) / len(items)),
                "students": len(items),
                "at_risk": sum(item["status"] == "at_risk" for item in items),
                "developing": sum(item["status"] == "developing" for item in items),
                "mastered": sum(item["status"] == "mastered" for item in items),
                "top_error": errors.most_common(1)[0][0] if errors else None,
                "prerequisites": PREREQUISITES.get(name, []),
            }
        )
    keypoints.sort(key=lambda item: (-item["at_risk"], item["mastery"], -item["students"], item["name"]))

    groups = [
        {
            "key": f"{key}:{focus}",
            "type": key,
            "label": GROUP_META[key]["label"],
            "focus": focus,
            "student_ids": student_ids,
            "count": len(student_ids),
            "strategy": GROUP_META[key]["strategy"],
        }
        for (key, focus), student_ids in grouped.items()
    ]
    groups.sort(key=lambda item: (item["type"] == "transfer_ready", -item["count"], item["focus"]))
    active_students = sum(item["questions"] > 0 for item in student_rows)
    needs_intervention = sum(
        item["count"] for item in groups if item["type"] not in {"transfer_ready", "needs_diagnostic"}
    )
    return {
        "summary": {
            "members": len(students),
            "active_students": active_students,
            "attempts": len(attempts),
            "needs_intervention": needs_intervention,
            "independent_transfer": len(independent_transfer_students),
        },
        "keypoints": keypoints,
        "students": sorted(student_rows, key=lambda item: (-item["risk_keypoints"], item["overall_mastery"], item["name"])),
        "groups": groups,
    }


def suggest_intervention_questions(
    rows: list[dict[str, Any]],
    focus: str,
    group_type: str,
    attempted_question_ids: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    preferred = {
        "needs_diagnostic": ["易", "中", "难"],
        "prerequisite_gap": ["易", "中", "难"],
        "hint_dependent": ["中", "易", "难"],
        "needs_foundation": ["易", "中", "难"],
        "transfer_ready": ["难", "中", "易"],
    }.get(group_type, ["易", "中", "难"])
    order = {difficulty: index for index, difficulty in enumerate(preferred)}
    candidates = [row for row in rows if focus in (row.get("keypoint") or [])]
    candidates.sort(key=lambda row: (order.get(str(row.get("hard_level")), 9), str(row.get("ID"))))
    excluded = attempted_question_ids or set()
    fresh = [row for row in candidates if str(row.get("ID")) not in excluded]
    chosen = fresh[:limit]
    if len(chosen) < limit:
        chosen_ids = {str(row.get("ID")) for row in chosen}
        chosen.extend(row for row in candidates if str(row.get("ID")) not in chosen_ids)
    return chosen[:limit]
