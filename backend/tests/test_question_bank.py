from src.question_bank.service import bank_stats, get_question, is_contextual_follow_up, retrieve_context, search_questions


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


def test_retrieval_understands_natural_language_difficulty():
    easy = retrieve_context("推荐样本空间的基础题")
    assert easy
    assert all(row["hard_level"] == "易" for row in easy)
