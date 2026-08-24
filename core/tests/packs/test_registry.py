import pytest
from core.packs.registry import (
    install_pack,
    list_installed_packs,
    remove_pack,
    PackInstallError,
)

VALID_YAML = """\
name: sample-pack
version: 1.0.0
kind: intelligence
summary: A sample pack for tests
requires_core: ">=0.1.0,<0.2.0"
capabilities: []
permissions_rationale: No capabilities needed for this test fixture.
dependencies: []
"""


def _make_registry_pack(root, name="sample-pack", contents=VALID_YAML):
    pack_dir = root / "packs" / "registry" / name
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(contents, encoding="utf-8")
    return pack_dir


def _config(root):
    return {"paths": {"packs_installed": "packs/installed"}}


def test_install_copies_pack_and_returns_manifest(tmp_path):
    _make_registry_pack(tmp_path)
    manifest = install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    assert manifest.name == "sample-pack"
    assert (tmp_path / "packs" / "installed" / "sample-pack" / "pack.yaml").exists()


def test_install_unknown_pack_raises(tmp_path):
    with pytest.raises(PackInstallError, match="no pack named"):
        install_pack("does-not-exist", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_name_mismatch(tmp_path):
    _make_registry_pack(tmp_path, name="dir-name", contents=VALID_YAML)  # pack.yaml says sample-pack
    with pytest.raises(PackInstallError, match="does not match"):
        install_pack("dir-name", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_self_dependency(tmp_path):
    self_dep_yaml = VALID_YAML.replace("dependencies: []", "dependencies: [sample-pack]")
    _make_registry_pack(tmp_path, contents=self_dep_yaml)
    with pytest.raises(PackInstallError, match="itself as a dependency"):
        install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_unsafe_name_before_touching_disk(tmp_path):
    with pytest.raises(PackInstallError, match="slug"):
        install_pack("../../etc", config=_config(tmp_path), root=tmp_path)


def test_list_installed_returns_valid_and_invalid(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    broken_dir = tmp_path / "packs" / "installed" / "broken-pack"
    broken_dir.mkdir(parents=True)
    (broken_dir / "pack.yaml").write_text("name: only-a-name\n", encoding="utf-8")

    results = list_installed_packs(config=_config(tmp_path), root=tmp_path)
    by_dirname = {pack_dir.name: (manifest, error) for pack_dir, manifest, error in results}

    manifest, error = by_dirname["sample-pack"]
    assert manifest is not None and error is None

    manifest, error = by_dirname["broken-pack"]
    assert manifest is None and "failed schema validation" in error


def test_list_installed_empty_when_dir_missing(tmp_path):
    results = list_installed_packs(config=_config(tmp_path), root=tmp_path)
    assert results == []


def test_remove_deletes_installed_pack(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    removed = remove_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    assert removed is True
    assert not (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_remove_returns_false_when_not_installed(tmp_path):
    removed = remove_pack("never-installed", config=_config(tmp_path), root=tmp_path)
    assert removed is False


def test_list_installed_reports_malformed_yaml_without_raising(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    malformed_dir = tmp_path / "packs" / "installed" / "malformed-pack"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "pack.yaml").write_text(
        "name: [unbalanced\n  bad indentation:\nfoo\n", encoding="utf-8"
    )

    results = list_installed_packs(config=_config(tmp_path), root=tmp_path)
    by_dirname = {pack_dir.name: (manifest, error) for pack_dir, manifest, error in results}

    manifest, error = by_dirname["malformed-pack"]
    assert manifest is None
    assert error is not None
