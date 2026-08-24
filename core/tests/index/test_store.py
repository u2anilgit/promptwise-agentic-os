from core.index.models import CodeLocation
from core.index.store import (
    delete_file_rows,
    get_stored_mtime,
    indexed_files,
    open_store,
    query_symbol,
    replace_file_rows,
)


def _config(tmp_path):
    return {"index": {"db_path": str(tmp_path / "code_index.sqlite3")}}


def test_get_stored_mtime_is_none_when_never_indexed(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    assert get_stored_mtime(conn, "a.py") is None


def test_replace_file_rows_then_query_roundtrips(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    locs = [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")]
    replace_file_rows(conn, "a.py", 123.0, locs)

    assert get_stored_mtime(conn, "a.py") == 123.0
    results = query_symbol(conn, "foo")
    assert len(results) == 1
    assert results[0].symbol == "foo"
    assert results[0].file == "a.py"


def test_replace_file_rows_drops_old_rows_for_that_file(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="old", kind="function")])
    replace_file_rows(conn, "a.py", 2.0, [CodeLocation(file="a.py", line=5, symbol="new", kind="function")])

    assert query_symbol(conn, "old") == []
    assert len(query_symbol(conn, "new")) == 1
    assert get_stored_mtime(conn, "a.py") == 2.0


def test_delete_file_rows_removes_everything_for_that_file(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")])
    delete_file_rows(conn, "a.py")

    assert query_symbol(conn, "foo") == []
    assert get_stored_mtime(conn, "a.py") is None


def test_query_symbol_ranks_exact_match_before_substring(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(
        conn,
        "a.py",
        1.0,
        [
            CodeLocation(file="a.py", line=1, symbol="foo_helper", kind="function"),
            CodeLocation(file="a.py", line=5, symbol="foo", kind="function"),
        ],
    )
    results = query_symbol(conn, "foo")
    assert [r.symbol for r in results] == ["foo", "foo_helper"]


def test_query_symbol_filters_by_kind(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(
        conn,
        "a.py",
        1.0,
        [
            CodeLocation(file="a.py", line=1, symbol="Foo", kind="class"),
            CodeLocation(file="a.py", line=5, symbol="Foo", kind="function"),
        ],
    )
    results = query_symbol(conn, "Foo", kind="class")
    assert len(results) == 1
    assert results[0].kind == "class"


def test_indexed_files_lists_every_file_with_rows(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")])
    replace_file_rows(conn, "b.py", 1.0, [])  # a file that parsed but defined nothing
    assert indexed_files(conn) == {"a.py", "b.py"}
