import os
import tempfile
from pathlib import Path

import pytest

from core.index.query import query_code_index


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _symlinks_supported() -> bool:
    """Symlink creation needs a privilege the sandbox may not have (e.g.
    Windows without Developer Mode/admin) — probe once at collection time,
    same convention as core/tests/packs/test_registry.py."""
    with tempfile.TemporaryDirectory() as probe_root:
        target = Path(probe_root) / "target"
        target.mkdir()
        link = Path(probe_root) / "link"
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except OSError:
            return False


requires_symlinks = pytest.mark.skipif(
    not _symlinks_supported(), reason="symlinks not supported in this environment"
)


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


def test_query_code_index_on_root_that_is_a_file_returns_empty(tmp_path):
    """root.exists() is true for a file too — must check is_dir(), not
    just existence, or open_store's `.promptwise` mkdir raises."""
    a_file = tmp_path / "not_a_directory.py"
    _write(a_file, "def alpha():\n    pass\n")
    assert query_code_index("alpha", root=a_file) == []


def test_query_code_index_survives_an_unreadable_file(tmp_path, monkeypatch):
    """A file-level I/O error (permission-denied, broken symlink, vanish
    race between stat() and read) must not abort the whole query — the
    file-level twin of the directory-level PermissionError handling."""
    _write(tmp_path / "good.py", "def alpha():\n    pass\n")
    _write(tmp_path / "locked.py", "def beta():\n    pass\n")

    real_read_bytes = Path.read_bytes

    def flaky_read_bytes(self):
        if self.name == "locked.py":
            raise PermissionError("denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].symbol == "alpha"


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


def test_query_code_index_prunes_ignored_directories_without_walking_into_them(tmp_path, monkeypatch):
    """Ignored dirs must be pruned from the walk itself (dirnames filtered
    before recursion), not just filtered out of the results after the
    walk already descended into them — a large vendored node_modules tree
    is a real cost otherwise."""
    _write(tmp_path / "real.py", "def alpha():\n    pass\n")
    _write(tmp_path / "node_modules" / "deep" / "vendored.py", "def alpha():\n    pass\n")

    real_scandir = os.scandir
    scanned_dirs = []

    def tracking_scandir(path="."):
        scanned_dirs.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", tracking_scandir)

    query_code_index("alpha", root=tmp_path)

    assert not any("node_modules" in d for d in scanned_dirs)


def test_query_code_index_survives_a_permission_error_in_one_subdirectory(tmp_path, monkeypatch):
    """A PermissionError while walking one subtree must not crash the
    whole query — same 'handled state, not exception' convention already
    applied to the file-vanishes-mid-walk race."""
    _write(tmp_path / "good" / "a.py", "def alpha():\n    pass\n")
    (tmp_path / "restricted").mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if Path(path).name == "restricted":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].symbol == "alpha"


@requires_symlinks
def test_query_code_index_does_not_follow_a_symlinked_directory_cycle(tmp_path):
    """A symlink cycle under root (self-referencing, or an npm/pnpm-style
    workspace symlink back up the tree) must not recurse indefinitely."""
    _write(tmp_path / "real.py", "def alpha():\n    pass\n")
    cycle = tmp_path / "loop"
    os.symlink(tmp_path, cycle, target_is_directory=True)

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].file == str(tmp_path / "real.py")


def test_roots_sharing_one_index_database_do_not_evict_or_leak_each_other(tmp_path, monkeypatch):
    import core.index.query as query_module

    config = {"index": {"db_path": str(tmp_path / "shared.sqlite3")}}
    _write(tmp_path / "a" / "one.py", "def shared_name():\n    pass\n")
    _write(tmp_path / "b" / "two.py", "def shared_name():\n    pass\n")
    from_a = query_code_index("shared_name", root=tmp_path / "a", config=config)
    from_b = query_code_index("shared_name", root=tmp_path / "b", config=config)
    assert [Path(loc.file).name for loc in from_a] == ["one.py"]
    assert [Path(loc.file).name for loc in from_b] == ["two.py"]
    monkeypatch.setattr(query_module, "parse_file", lambda path: pytest.fail(f"evicted and reparsed {path}"))
    again = query_code_index("shared_name", root=tmp_path / "a", config=config)
    assert [Path(loc.file).name for loc in again] == ["one.py"]


def test_relative_and_absolute_root_share_the_incremental_index(tmp_path, monkeypatch):
    import core.index.query as query_module

    config = {"index": {"db_path": str(tmp_path / "idx.sqlite3")}}
    _write(tmp_path / "repo" / "m.py", "def thing():\n    pass\n")
    query_code_index("thing", root=tmp_path / "repo", config=config)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(query_module, "parse_file", lambda path: pytest.fail(f"reparsed {path}"))
    assert len(query_code_index("thing", root=Path("repo"), config=config)) == 1


def test_legacy_relative_keys_are_swept(tmp_path):
    from core.index.models import CodeLocation
    from core.index.store import indexed_files, open_store, replace_file_rows

    config = {"index": {"db_path": str(tmp_path / "idx.sqlite3")}}
    conn = open_store(config, root=tmp_path)
    replace_file_rows(conn, "repo/old.py", 1.0, [CodeLocation(file="repo/old.py", line=1, symbol="old", kind="function")])
    conn.close()
    _write(tmp_path / "repo" / "m.py", "def thing():\n    pass\n")
    query_code_index("thing", root=tmp_path / "repo", config=config)
    conn = open_store(config, root=tmp_path)
    try:
        assert "repo/old.py" not in indexed_files(conn)
    finally:
        conn.close()


def _make_junction(link: Path, target: Path) -> bool:
    """Windows directory junction (no admin privilege needed, unlike symlinks)."""
    import subprocess
    import sys

    if sys.platform != "win32":
        return False
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return proc.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_query_code_index_does_not_follow_a_junction_out_of_the_root(tmp_path):
    outside = tmp_path / "outside"
    _write(outside / "secret.py", "def outside_symbol():\n    pass\n")
    root = tmp_path / "repo"
    _write(root / "inside.py", "def inside_symbol():\n    pass\n")
    assert _make_junction(root / "linked", outside)
    config = {"index": {"db_path": str(tmp_path / "idx.sqlite3")}}
    assert query_code_index("outside_symbol", root=root, config=config) == []
    assert len(query_code_index("inside_symbol", root=root, config=config)) == 1
