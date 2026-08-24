from core.memory.extract import extract_facts


def _config():
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "memory": {"ollama_base_url": "http://127.0.0.1:11434", "extraction_tier_hint": "local-small"},
    }


def test_extract_facts_parses_a_valid_json_response():
    def fake_http_post(url, json_body, timeout=10.0):
        assert url.endswith("/api/generate")
        return {"response": '{"facts": [{"text": "user prefers pytest", "category": "preference"}]}'}

    facts = extract_facts("I always use pytest, never unittest", _config(), http_post=fake_http_post)
    assert facts == [{"text": "user prefers pytest", "category": "preference"}]


def test_extract_facts_falls_back_to_one_unclassified_fact_on_unreachable_ollama():
    def failing_http_post(url, json_body, timeout=10.0):
        raise OSError("connection refused")

    facts = extract_facts("some raw session text", _config(), http_post=failing_http_post)
    assert facts == [{"text": "some raw session text", "category": "unclassified"}]


def test_extract_facts_falls_back_to_one_unclassified_fact_on_invalid_json():
    def bad_json_http_post(url, json_body, timeout=10.0):
        return {"response": "not valid json at all"}

    facts = extract_facts("some raw session text", _config(), http_post=bad_json_http_post)
    assert facts == [{"text": "some raw session text", "category": "unclassified"}]


def test_extract_facts_empty_text_returns_empty_list():
    assert extract_facts("   ", _config()) == []
    assert extract_facts("", _config()) == []
