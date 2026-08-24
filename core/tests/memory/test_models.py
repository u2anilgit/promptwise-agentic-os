from core.memory.models import Fact


def test_fact_requires_all_non_defaulted_fields():
    fact = Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=1000.0)
    assert fact.text == "user prefers pytest"
    assert fact.category == "preference"
    assert fact.scope == "project"
    assert fact.root == "/repo"
    assert fact.created_at == 1000.0
    assert fact.id is None          # not yet persisted
    assert fact.session_id is None  # scope="project", no session
    assert fact.pii is False        # default


def test_fact_session_scope_takes_session_id_not_root():
    fact = Fact(text="working on the login bug", category="context", scope="session", session_id="abc123", created_at=1000.0)
    assert fact.scope == "session"
    assert fact.session_id == "abc123"
    assert fact.root is None
