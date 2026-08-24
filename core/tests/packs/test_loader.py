import pytest
from core.packs.loader import load_pack_manifest, PackValidationError

VALID_YAML = """\
name: repo-intelligence
version: 1.0.0
kind: intelligence
summary: Reverse-engineers an existing repo into docs
requires_core: ">=0.1.0,<0.2.0"
capabilities:
  - fs:read
permissions_rationale: Needs fs:read to scan the target repo.
dependencies: []
"""


def _write_manifest(tmp_path, contents, dirname="a-pack"):
    pack_dir = tmp_path / dirname
    pack_dir.mkdir()
    (pack_dir / "pack.yaml").write_text(contents, encoding="utf-8")
    return pack_dir


def test_load_valid_manifest(tmp_path):
    pack_dir = _write_manifest(tmp_path, VALID_YAML)
    manifest = load_pack_manifest(pack_dir, core_version="0.1.0")
    assert manifest.name == "repo-intelligence"
    assert manifest.kind == "intelligence"


def test_missing_pack_yaml_raises(tmp_path):
    pack_dir = tmp_path / "empty-pack"
    pack_dir.mkdir()
    with pytest.raises(PackValidationError, match="no pack.yaml"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_malformed_schema_raises(tmp_path):
    pack_dir = _write_manifest(tmp_path, "name: only-a-name\n", dirname="broken-pack")
    with pytest.raises(PackValidationError, match="failed schema validation"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_requires_core_out_of_range_raises(tmp_path):
    pack_dir = _write_manifest(tmp_path, VALID_YAML)
    with pytest.raises(PackValidationError, match="requires_core"):
        load_pack_manifest(pack_dir, core_version="0.9.0")


def test_invalid_requires_core_clause_raises(tmp_path):
    bad_yaml = VALID_YAML.replace('">=0.1.0,<0.2.0"', '"~0.1.0"')
    pack_dir = _write_manifest(tmp_path, bad_yaml, dirname="bad-range-pack")
    with pytest.raises(PackValidationError, match="requires_core"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_malformed_yaml_syntax_raises_pack_validation_error(tmp_path):
    # Genuinely malformed YAML syntax (unbalanced flow mapping) — this must
    # raise yaml.YAMLError from yaml.safe_load, not just fail schema
    # validation on a parseable-but-invalid document.
    bad_yaml = "name: broken\ncapabilities: [fs:read\n"
    pack_dir = _write_manifest(tmp_path, bad_yaml, dirname="malformed-yaml-pack")
    with pytest.raises(PackValidationError, match="could not be read/parsed"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_defaults_to_running_core_version(tmp_path, monkeypatch):
    # Patched to a value distinct from the real package version (0.1.0) so
    # this test would fail if load_pack_manifest stopped reading
    # core.__version__ and fell back to a hardcoded default instead.
    import core
    monkeypatch.setattr(core, "__version__", "0.1.5")
    pack_dir = _write_manifest(tmp_path, VALID_YAML)  # requires_core ">=0.1.0,<0.2.0" covers 0.1.5
    manifest = load_pack_manifest(pack_dir)  # no core_version passed
    assert manifest.name == "repo-intelligence"
