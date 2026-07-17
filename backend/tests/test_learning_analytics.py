from src.question_bank.analytics import (
    build_learning_profile,
    build_teaching_insights,
    experiment_catalog,
    select_layered_questions,
)
from src.question_bank.service import load_questions


def _question_with(keypoint: str):
    return next(row for row in load_questions() if keypoint in row["keypoint"])


def test_empty_profile_starts_with_foundation_path():
    profile = build_learning_profile(load_questions(), [])

    assert profile["summary"]["evidence_level"] == "low"
    assert profile["summary"]["next_focus"] == "样本空间"
    assert profile["path"]
    assert profile["path"][0]["question_ids"]


def test_repeated_errors_create_grounded_warning_and_path():
    row = _question_with("贝叶斯公式")
    attempts = [
        {
            "question_id": row["ID"],
            "verdict": "incorrect",
            "error_type": "公式选择错误",
            "hint_count": 2,
            "attempt_no": 2,
        },
        {
            "question_id": row["ID"],
            "verdict": "partial",
            "error_type": "条件遗漏",
            "hint_count": 1,
            "attempt_no": 1,
        },
    ]

    profile = build_learning_profile(load_questions(), attempts)
    bayes = next(item for item in profile["mastery"] if item["name"] == "贝叶斯公式")

    assert bayes["status"] == "at_risk"
    assert bayes["score"] < 60
    assert any(alert["keypoint"] == "贝叶斯公式" for alert in profile["alerts"])
    assert any(step["keypoint"] == "贝叶斯公式" for step in profile["path"])


def test_layered_selection_and_teacher_insights_are_explainable():
    rows = [
        row for row in load_questions()
        if "正态分布" in row["keypoint"]
    ][:30]
    selected = select_layered_questions(rows)
    insights = build_teaching_insights(selected, [])

    assert len(selected) <= 12
    assert set(insights["layers"]) == {"易", "中", "难"}
    assert "正态分布" in insights["keypoints"]
    assert isinstance(insights["warnings"], list)


def test_every_experiment_links_back_to_corpus_questions():
    catalog = experiment_catalog(load_questions())

    assert len(catalog) == 8
    assert all(item["keypoints"] for item in catalog)
    assert all(item["question_ids"] for item in catalog)
