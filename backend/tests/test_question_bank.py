from src.question_bank.handler import _carried_question_ids, _grounded_tutor_fallback
from src.question_bank.service import (
    bank_stats,
    get_question,
    is_contextual_follow_up,
    requested_recommendation_count,
    retrieve_context,
    search_questions,
)


def test_bank_has_expected_range_and_count():
    assert bank_stats()["total"] == 1007
    assert get_question("P000001")["ID"] == "P000001"
    assert get_question("P001007")["ID"] == "P001007"


def test_search_by_id_and_keypoint():
    rows, total = search_questions("P000001")
    assert total == 1
    assert rows[0]["ID"] == "P000001"

    rows, total = search_questions("样本空间", page_size=10)
    assert total > 0
    assert "样本空间" in rows[0]["keypoint"]


def test_embedded_question_id_is_retrieved_first():
    rows = retrieve_context("请分步骤讲解 P000001，并指出易错点")
    assert rows[0]["ID"] == "P000001"


def test_natural_language_question_resolves_embedded_keypoint():
    rows = retrieve_context("如何判断一道题该用贝叶斯公式？")
    assert rows
    assert all("贝叶斯公式" in row["keypoint"] for row in rows)


def test_follow_up_detection_does_not_carry_context_into_new_topic():
    assert is_contextual_follow_up("这一步为什么要除以这个概率？")
    assert is_contextual_follow_up("再讲慢一点")
    assert not is_contextual_follow_up("请讲解 P000001")
    assert not is_contextual_follow_up("条件概率和全概率公式有什么区别？")
    assert not is_contextual_follow_up("为什么正态分布很重要？")


def test_retrieval_understands_natural_language_difficulty():
    easy = retrieve_context("推荐样本空间的基础题")
    assert easy
    assert all(row["hard_level"] == "易" for row in easy)


def test_retrieval_balances_multiple_named_keypoints_and_prefers_specific_phrase():
    compared = retrieve_context("条件概率和全概率公式有什么区别？", limit=6)
    assert any("条件概率" in row["keypoint"] for row in compared[:2])
    assert any("全概率公式" in row["keypoint"] for row in compared[:2])
    assert compared[0]["hard_level"] == "易"

    sample_space = retrieve_context("推荐3道样本空间基础题", limit=3)
    assert len(sample_space) == 3
    assert all("样本空间" in row["keypoint"] for row in sample_space)


def test_recommendation_count_understands_arabic_and_chinese_numbers():
    assert requested_recommendation_count("推荐3道样本空间基础题") == 3
    assert requested_recommendation_count("请推荐三道样本空间题") == 3
    assert requested_recommendation_count("推荐一些基础题") == 6
    assert requested_recommendation_count("推荐20道题") == 8


def test_follow_up_can_select_one_source_by_position():
    sources = ["P000001", "P000002", "P000003"]
    assert _carried_question_ids("第二题怎么算？", sources) == ["P000002"]
    assert _carried_question_ids("这几题再讲讲", sources) == sources


def test_non_full_fallback_never_exposes_standard_solution():
    question = get_question("P000080")
    for mode in ("hint", "check", "step"):
        fallback = _grounded_tutor_fallback(question, mode)
        assert "标准解析" not in fallback
        assert str(question["answer"]) not in fallback
    assert "标准解析" in _grounded_tutor_fallback(question, "full")
