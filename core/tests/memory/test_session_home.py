"""Root-less (session) memory calls without an explicit config resolve against the user's PromptWise home,
not whatever directory the process happens to run in."""
import pytest

from core.memory.memory import query_memory, record_memory


def _fake_post(url, payload, timeout=None):
    raise OSError("no model in tests")


@pytest.fixture
def places(tmp_path, monkeypatch):
    cwd = tmp_path / "somewhere"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PROMPTWISE_HOME", str(home))
    monkeypatch.setenv("PROMPTWISE_MEMORY__QDRANT_URL", "http://127.0.0.1:9")
    return cwd, home


def test_session_scope_without_config_uses_the_user_home(places):
    cwd, home = places
    record_memory("The user prefers tabs.", scope="session", session_id="s1", http_post=_fake_post)
    query_memory("tabs", scope="session", session_id="s1", http_post=_fake_post)
    assert (home / ".promptwise" / "memory.sqlite3").exists()
    assert not (cwd / ".promptwise" / "memory.sqlite3").exists()


def test_project_scope_still_uses_the_project_root(places, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _, home = places
    record_memory("Uses pytest.", scope="project", root=str(project), http_post=_fake_post)
    assert (project / ".promptwise" / "memory.sqlite3").exists()
    assert not (home / ".promptwise" / "memory.sqlite3").exists()
