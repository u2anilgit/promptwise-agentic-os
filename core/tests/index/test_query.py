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
