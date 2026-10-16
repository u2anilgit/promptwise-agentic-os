import textwrap

from core.security.supply_chain import (
    check_dependencies,
    find_known_bad,
    load_known_bad,
    parse_lockfile,
)

HASH = "sha256:" + "a" * 64


def _write(path, content):
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _config(tmp_path, known_bad=True, lock=True):
    cfg = {"security": {}}
    if known_bad:
        _write(
            tmp_path / "bad.yaml",
            """
            packages:
              - package: LiteLLM
                versions: ["1.82.7", "1.82.8"]
                reason: malicious release
                reference: https://example.test/advisory
            """,
        )
        cfg["security"]["known_bad_packages_path"] = str(tmp_path / "bad.yaml")
    if lock:
        _write(
            tmp_path / "req.lock",
            f"""
            # generated
            pydantic==2.8.0 \
                --hash={HASH}
            pyyaml==6.0.1 \
                --hash={HASH} \
                --hash={HASH}
            """,
        )
        cfg["security"]["lockfile_path"] = str(tmp_path / "req.lock")
    return cfg


def test_load_known_bad_parses_entries(tmp_path):
    entries = load_known_bad(_config(tmp_path))
    assert len(entries) == 1
    assert entries[0].package == "litellm"  # canonicalized
    assert entries[0].versions == ["1.82.7", "1.82.8"]


def test_load_known_bad_missing_file_returns_empty(tmp_path):
    assert load_known_bad({"security": {"known_bad_packages_path": str(tmp_path / "nope.yaml")}}) == []


def test_find_known_bad_matches_canonical_names_and_versions(tmp_path):
    entries = load_known_bad(_config(tmp_path))
    hits = find_known_bad({"LiteLLM": "1.82.8"}, entries)
    assert [(h.package, h.installed_version) for h in hits] == [("litellm", "1.82.8")]
    assert find_known_bad({"litellm": "1.82.6"}, entries) == []


def test_parse_lockfile_reads_pins_and_hashes(tmp_path):
    _config(tmp_path)
    entries = parse_lockfile(tmp_path / "req.lock")
    assert [(e.name, e.version, len(e.hashes)) for e in entries] == [("pydantic", "2.8.0", 1), ("pyyaml", "6.0.1", 2)]


def test_check_dependencies_fails_on_known_bad_installed_version(tmp_path):
    result = check_dependencies(_config(tmp_path), installed={"litellm": "1.82.7", "pydantic": "2.8.0", "pyyaml": "6.0.1"})
    assert result.name == "deps.integrity"
    assert result.status == "FAIL"
    assert "litellm" in result.message and "1.82.7" in result.message


def test_check_dependencies_passes_when_clean_and_locked(tmp_path):
    result = check_dependencies(_config(tmp_path), installed={"pydantic": "2.8.0", "pyyaml": "6.0.1"})
    assert result.status == "PASS"


def test_check_dependencies_warns_on_lock_drift(tmp_path):
    result = check_dependencies(_config(tmp_path), installed={"pydantic": "2.9.0", "pyyaml": "6.0.1"})
    assert result.status == "WARN"
    assert "pydantic" in result.message


def test_check_dependencies_warns_when_lock_entry_has_no_hash(tmp_path):
    cfg = _config(tmp_path)
    _write(tmp_path / "req.lock", "pydantic==2.8.0\n")
    result = check_dependencies(cfg, installed={"pydantic": "2.8.0"})
    assert result.status == "WARN"
    assert "hash" in result.message


def test_check_dependencies_warns_when_no_lockfile(tmp_path):
    result = check_dependencies(_config(tmp_path, lock=False), installed={"pydantic": "2.8.0"})
    assert result.status == "WARN"
    assert "lock" in result.message


def test_known_bad_beats_lock_warning(tmp_path):
    result = check_dependencies(_config(tmp_path, lock=False), installed={"litellm": "1.82.8"})
    assert result.status == "FAIL"
