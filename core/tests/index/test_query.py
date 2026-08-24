from pathlib import Path

from core.index.query import query_code_index


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_query_code_index_finds_definitions_across_multiple_files_and_languages(tmp_path):
    _write(tmp_path / "pkg" / "a.py", "def alpha():\n    pass\n")
    _write(tmp_path / "pkg" / "b.py", "class Beta:\n    def gamma(self):\n        pass\n")
    _write(tmp_path / "web" / "c.ts", "function delta() { return 1; }\n")

    assert [loc.symbol for loc in query_code_index("alpha", root=tmp_path)] == ["alpha"]
    beta_results = query_code_index("Beta", root=tmp_path)
    assert len(beta_results) == 1
    assert beta_results[0].kind == "class"
    assert query_code_index("gamma", root=tmp_path)[0].line == 2
    assert query_code_index("delta", root=tmp_path)[0].file == str(tmp_path / "web" / "c.ts")


def test_query_code_index_on_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert query_code_index("anything", root=missing) == []


def test_query_code_index_symbol_not_found_returns_empty(tmp_path):
    _write(tmp_path / "a.py", "def alpha():\n    pass\n")
    assert query_code_index("nonexistent_symbol", root=tmp_path) == []


def test_query_code_index_survives_a_syntax_error_in_one_file(tmp_path):
    _write(tmp_path / "good.py", "def alpha():\n    pass\n")
    _write(tmp_path / "bad.py", "def broken(:\n")

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].symbol == "alpha"


def test_query_code_index_picks_up_an_edit_via_mtime_invalidation(tmp_path):
    target = tmp_path / "a.py"
    _write(target, "def old_name():\n    pass\n")
    query_code_index("old_name", root=tmp_path)  # first index

    import time

    time.sleep(0.01)  # ensure the mtime actually advances on fast filesystems
    _write(target, "def new_name():\n    pass\n")

    assert query_code_index("old_name", root=tmp_path) == []
    assert len(query_code_index("new_name", root=tmp_path)) == 1


def test_query_code_index_drops_rows_for_a_deleted_file(tmp_path):
    target = tmp_path / "a.py"
    _write(target, "def alpha():\n    pass\n")
    query_code_index("alpha", root=tmp_path)  # first index

    target.unlink()
    assert query_code_index("alpha", root=tmp_path) == []


def test_query_code_index_skips_ignored_directories(tmp_path):
    _write(tmp_path / "real.py", "def alpha():\n    pass\n")
    _write(tmp_path / "node_modules" / "vendored.py", "def alpha():\n    pass\n")
    _write(tmp_path / ".git" / "hooks.py", "def alpha():\n    pass\n")

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].file == str(tmp_path / "real.py")
