from src.question_bank.service import bank_stats, get_question, retrieve_context, search_questions


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
