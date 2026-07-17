from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable


# The corpus identifies concepts but does not encode prerequisite edges.  Keep a
# small, auditable curriculum graph here; concepts outside it still participate
# in mastery scoring and recommendation through their corpus tags.
PREREQUISITES: dict[str, list[str]] = {
    "随机事件": ["样本空间"],
    "事件之间的运算": ["随机事件"],
    "古典概型": ["样本空间", "随机事件"],
    "条件概率": ["随机事件"],
    "乘法公式": ["条件概率"],
    "全概率公式": ["条件概率"],
    "贝叶斯公式": ["全概率公式", "条件概率"],
    "随机变量": ["随机事件"],
    "离散型随机变量": ["随机变量"],
    "连续型随机变量": ["随机变量"],
    "概率分布列": ["离散型随机变量"],
    "概率密度函数": ["连续型随机变量"],
    "分布函数": ["随机变量"],
    "数学期望": ["概率分布列", "概率密度函数"],
    "方差": ["数学期望"],
    "协方差": ["方差"],
    "联合分布列": ["离散型随机变量"],
    "联合密度函数": ["连续型随机变量"],
    "条件分布": ["联合分布函数", "条件概率"],
    "二项分布": ["离散型随机变量", "概率分布列"],
    "泊松分布": ["离散型随机变量", "概率分布列"],
    "正态分布": ["连续型随机变量", "概率密度函数"],
    "大数定律": ["数学期望", "方差"],
    "中心极限定理": ["正态分布", "数学期望", "方差"],
    "样本": ["随机变量"],
    "简单随机样本": ["样本"],
    "统计量": ["简单随机样本"],
    "样本均值": ["统计量", "数学期望"],
    "样本方差": ["统计量", "方差"],
    "点估计": ["统计量"],
    "最大似然估计": ["点估计", "似然函数"],
    "充分统计量": ["统计量", "似然函数"],
    "置信区间": ["点估计", "抽样分布"],
    "假设检验": ["统计量", "抽样分布"],
}

EXPERIMENT_KEYPOINTS: dict[str, list[str]] = {
    "coin": ["大数定律", "概率的统计定义"],
    "binomial": ["二项分布", "概率分布列"],
    "normal": ["正态分布", "概率密度函数"],
    "clt": ["中心极限定理", "样本均值"],
    "bayes": ["贝叶斯公式", "条件概率"],
    "confidence": ["置信区间", "样本均值"],
    "montecarlo": ["蒙特卡洛法", "几何概型"],
    "poisson": ["泊松定理", "二项分布", "泊松分布"],
}

KEYPOINT_EXPERIMENT = {
    keypoint: experiment_id
    for experiment_id, keypoints in EXPERIMENT_KEYPOINTS.items()
    for keypoint in keypoints
}

VERDICT_SCORE = {
    "correct": 1.0,
    "partial": 0.62,
    "incorrect": 0.12,
    "needs_review": 0.35,
}

DIFFICULTY_ORDER = {"易": 0, "中": 1, "难": 2}


def _attempt_value(attempt: dict[str, Any]) -> float:
    base = VERDICT_SCORE.get(str(attempt.get("verdict") or ""), 0.35)
    hint_penalty = min(int(attempt.get("hint_count") or 0), 4) * 0.035
    return max(0.0, base - hint_penalty)


def _question_lookup(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ID")): row for row in rows if row.get("ID")}


def _keypoint_ids(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        for name, keypoint_id in zip(row.get("keypoint") or [], row.get("keypoint_ids") or []):
            # A few source IDs are reused for different labels.  The readable
            # name remains canonical while the first stable ID is retained.
            result.setdefault(str(name), str(keypoint_id))
    return result


def _questions_for_keypoint(
    rows: Iterable[dict[str, Any]],
    keypoint: str,
    *,
    exclude: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    excluded = exclude or set()
    candidates = [
        row for row in rows
        if keypoint in (row.get("keypoint") or []) and str(row.get("ID")) not in excluded
    ]
    candidates.sort(key=lambda row: (DIFFICULTY_ORDER.get(str(row.get("hard_level")), 9), str(row.get("ID"))))
    return candidates[:limit]


def build_learning_profile(
    rows: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    lookup = _question_lookup(rows)
    ids = _keypoint_ids(rows)
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attempted_question_ids: set[str] = set()

    # Callers provide newest-first attempts.  Recency and repeated recovery both
    # remain visible instead of reducing a question to a single binary result.
    for index, attempt in enumerate(attempts):
        question_id = str(attempt.get("question_id") or "")
        row = lookup.get(question_id)
        if not row:
            continue
        attempted_question_ids.add(question_id)
        recency_weight = max(0.45, 1.0 - index * 0.012)
        for keypoint in row.get("keypoint") or []:
            evidence[str(keypoint)].append(
                {
                    **attempt,
                    "question_id": question_id,
                    "value": _attempt_value(attempt),
                    "weight": recency_weight,
                }
            )

    mastery: list[dict[str, Any]] = []
    mastery_by_name: dict[str, dict[str, Any]] = {}
    for keypoint, items in evidence.items():
        total_weight = sum(item["weight"] for item in items) or 1
        score = round(100 * sum(item["value"] * item["weight"] for item in items) / total_weight)
        questions = {item["question_id"] for item in items}
        confidence = min(100, round(len(questions) / 5 * 100 + min(len(items) - len(questions), 3) * 6))
        error_counts = Counter(
            str(item.get("error_type")) for item in items if item.get("error_type")
        )
        newest = items[: min(3, len(items))]
        oldest = items[-min(3, len(items)) :]
        trend_delta = sum(item["value"] for item in newest) / len(newest) - sum(
            item["value"] for item in oldest
        ) / len(oldest)
        trend = "up" if trend_delta > 0.12 else "down" if trend_delta < -0.12 else "steady"
        status = "mastered" if score >= 80 and confidence >= 35 else "developing" if score >= 60 else "at_risk"
        item = {
            "id": ids.get(keypoint, keypoint),
            "name": keypoint,
            "score": score,
            "confidence": confidence,
            "status": status,
            "trend": trend,
            "attempts": len(items),
            "questions": len(questions),
            "correct_attempts": sum(item.get("verdict") == "correct" for item in items),
            "hint_count": sum(int(item.get("hint_count") or 0) for item in items),
            "top_error": error_counts.most_common(1)[0][0] if error_counts else None,
            "prerequisites": PREREQUISITES.get(keypoint, []),
        }
        mastery.append(item)
        mastery_by_name[keypoint] = item

    mastery.sort(key=lambda item: (item["score"], -item["questions"], item["name"]))

    alerts: list[dict[str, Any]] = []
    for item in mastery:
        if item["status"] != "at_risk" or item["attempts"] < 2:
            continue
        weak_prerequisites = [
            name for name in item["prerequisites"]
            if name in mastery_by_name and mastery_by_name[name]["score"] < 60
        ]
        severity = "high" if item["score"] < 40 and item["attempts"] >= 3 else "medium"
        if weak_prerequisites:
            title = f"{item['name']}可能存在前置知识断层"
            message = f"当前掌握度 {item['score']}%，同时前置知识“{'、'.join(weak_prerequisites)}”尚未稳定。"
            recommendation = f"先回补{'、'.join(weak_prerequisites)}，再重新练习{item['name']}。"
        else:
            title = f"{item['name']}需要巩固"
            error_note = f"，主要表现为{item['top_error']}" if item["top_error"] else ""
            message = f"基于 {item['questions']} 道题、{item['attempts']} 次作答，当前掌握度为 {item['score']}%{error_note}。"
            recommendation = "先完成一组基础题，再用中等题检查是否能独立迁移。"
        alerts.append(
            {
                "severity": severity,
                "keypoint": item["name"],
                "title": title,
                "message": message,
                "recommendation": recommendation,
                "evidence": {
                    "attempts": item["attempts"],
                    "questions": item["questions"],
                    "hints": item["hint_count"],
                    "top_error": item["top_error"],
                },
            }
        )
    alerts.sort(key=lambda item: (item["severity"] != "high", mastery_by_name[item["keypoint"]]["score"]))

    path: list[dict[str, Any]] = []
    risk_candidates = [item for item in mastery if item["status"] == "at_risk"]
    risk_candidates.sort(
        key=lambda item: (
            item["score"],
            -len(PREREQUISITES.get(item["name"], [])),
            -len(item["name"]),
        )
    )
    focus = risk_candidates[0]["name"] if risk_candidates else mastery[0]["name"] if mastery else "样本空间"
    focus_item = mastery_by_name.get(focus)
    prerequisites = [
        name for name in PREREQUISITES.get(focus, [])
        if name not in mastery_by_name or mastery_by_name[name]["score"] < 65
    ]
    ordered_concepts = [*prerequisites, focus]
    seen_concepts: set[str] = set()
    order = 1
    for concept in ordered_concepts:
        if concept in seen_concepts:
            continue
        seen_concepts.add(concept)
        current = mastery_by_name.get(concept)
        questions = _questions_for_keypoint(rows, concept, exclude=attempted_question_ids, limit=3)
        if not questions:
            questions = _questions_for_keypoint(rows, concept, limit=3)
        path.append(
            {
                "order": order,
                "type": "review" if concept in prerequisites else "practice",
                "title": f"{'回补' if concept in prerequisites else '巩固'}：{concept}",
                "keypoint": concept,
                "reason": (
                    f"这是“{focus}”的前置知识，先稳定基础再继续。"
                    if concept in prerequisites
                    else f"当前掌握度 {current['score']}%，用分层练习确认是否真正掌握。"
                    if current
                    else "从课程起点建立第一份可测量的学习证据。"
                ),
                "question_ids": [row["ID"] for row in questions],
                "difficulty": [row.get("hard_level") for row in questions],
                "experiment_id": KEYPOINT_EXPERIMENT.get(concept),
                "completed": bool(current and current["score"] >= 80 and current["confidence"] >= 35),
            }
        )
        order += 1
    experiment_id = KEYPOINT_EXPERIMENT.get(focus)
    if experiment_id and not any(item.get("experiment_id") == experiment_id for item in path[:-1]):
        path.append(
            {
                "order": order,
                "type": "experiment",
                "title": f"用实验验证：{focus}",
                "keypoint": focus,
                "reason": "调节参数并记录观察，把公式结论转化为可解释的现象。",
                "question_ids": [],
                "difficulty": [],
                "experiment_id": experiment_id,
                "completed": False,
            }
        )

    assessed = len(mastery)
    overall = round(sum(item["score"] * item["confidence"] for item in mastery) / sum(
        item["confidence"] for item in mastery
    )) if mastery and sum(item["confidence"] for item in mastery) else 0
    return {
        "summary": {
            "overall_mastery": overall,
            "assessed_keypoints": assessed,
            "strong_keypoints": sum(item["status"] == "mastered" for item in mastery),
            "risk_keypoints": sum(item["status"] == "at_risk" for item in mastery),
            "next_focus": focus,
            "evidence_level": "high" if len(attempted_question_ids) >= 12 else "medium" if len(attempted_question_ids) >= 5 else "low",
        },
        "evidence": {
            "attempts": len(attempts),
            "questions": len(attempted_question_ids),
            "keypoints": assessed,
        },
        "mastery": mastery,
        "alerts": alerts[:8],
        "path": path,
    }


def select_layered_questions(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Keep explicit IDs first, then balance retrieved rows across difficulty."""
    if len(rows) <= 3:
        return rows[:limit]
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("hard_level") or "中")].append(row)
    targets = {"易": 4, "中": 5, "难": 3}
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for difficulty in ("易", "中", "难"):
        for row in buckets[difficulty][: targets[difficulty]]:
            if row["ID"] not in seen:
                chosen.append(row)
                seen.add(row["ID"])
    for row in rows:
        if len(chosen) >= limit:
            break
        if row["ID"] not in seen:
            chosen.append(row)
            seen.add(row["ID"])
    return chosen[:limit]


def build_teaching_insights(
    rows: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    row_ids = {str(row.get("ID")) for row in rows}
    keypoints = sorted({str(kp) for row in rows for kp in (row.get("keypoint") or [])})
    diagnostics = [item for item in attempts if str(item.get("question_id")) in row_ids]
    verdicts = Counter(str(item.get("verdict")) for item in diagnostics)
    errors = Counter(str(item.get("error_type")) for item in diagnostics if item.get("error_type"))
    layers = {
        difficulty: [row["ID"] for row in rows if row.get("hard_level") == difficulty]
        for difficulty in ("易", "中", "难")
    }
    warnings: list[dict[str, Any]] = []
    if not layers["易"]:
        warnings.append({"severity": "medium", "title": "缺少基础诊断题", "detail": "当前材料没有易题，无法快速确认学生是否具备前置基础。"})
    if not layers["难"]:
        warnings.append({"severity": "low", "title": "缺少迁移挑战题", "detail": "当前材料没有难题，难以观察学生能否把概念迁移到复杂情境。"})
    if diagnostics:
        risk_count = verdicts["incorrect"] + verdicts["partial"]
        if risk_count / len(diagnostics) >= 0.4:
            common = errors.most_common(1)[0][0] if errors else "作答不完整"
            warnings.insert(0, {
                "severity": "high",
                "title": "历史作答显示明显认知风险",
                "detail": f"相关题目有 {risk_count}/{len(diagnostics)} 次未完全正确，最常见问题是“{common}”。",
            })
    sparse = [kp for kp in keypoints if sum(kp in (row.get("keypoint") or []) for row in rows) < 2]
    if sparse:
        warnings.append({"severity": "low", "title": "部分知识点证据较少", "detail": f"{'、'.join(sparse[:4])}在当前教学包中只有 1 道题，建议补充课堂追问。"})
    return {
        "keypoints": keypoints,
        "prerequisites": {kp: PREREQUISITES.get(kp, []) for kp in keypoints if PREREQUISITES.get(kp)},
        "layers": layers,
        "diagnostics": {
            "attempts": len(diagnostics),
            "verdicts": dict(verdicts),
            "error_types": [{"name": name, "count": count} for name, count in errors.most_common(5)],
        },
        "warnings": warnings,
    }


def experiment_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for experiment_id, keypoints in EXPERIMENT_KEYPOINTS.items():
        related = [
            row for row in rows
            if any(keypoint in (row.get("keypoint") or []) for keypoint in keypoints)
        ]
        related.sort(key=lambda row: (DIFFICULTY_ORDER.get(str(row.get("hard_level")), 9), row["ID"]))
        catalog.append({
            "experiment_id": experiment_id,
            "keypoints": keypoints,
            "question_ids": [row["ID"] for row in related[:4]],
        })
    return catalog
