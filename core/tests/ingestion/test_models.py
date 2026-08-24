from core.ingestion.models import IngestionResult


def test_ingestion_result_defaults():
    result = IngestionResult(root="/repo")
    assert result.root == "/repo"
    assert result.code_index_refreshed is False
    assert result.facts_recorded == 0
    assert result.facts_failed == 0
    assert result.errors == []


def test_ingestion_result_all_fields():
    result = IngestionResult(
        root="/repo", code_index_refreshed=True, facts_recorded=3, facts_failed=1,
        errors=["record_memory failed for session_texts[2]: connection refused"],
    )
    assert result.code_index_refreshed is True
    assert result.facts_recorded == 3
    assert result.facts_failed == 1
    assert len(result.errors) == 1
