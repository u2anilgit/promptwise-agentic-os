import os
import tempfile
from pathlib import Path

import pytest
from core.packs.registry import (
    install_pack,
    list_installed_packs,
    remove_pack,
    PackInstallError,
)


def _symlinks_supported() -> bool:
    """Symlink creation needs a privilege the sandbox may not have (e.g.
    Windows without Developer Mode/admin) — probe once at collection time,
    same convention as this project's semgrep/gitleaks skipif tests."""
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


def _config():
    return {"paths": {"packs_installed": "packs/installed"}}


def test_install_copies_pack_and_returns_manifest(tmp_path):
    _make_registry_pack(tmp_path)
    manifest = install_pack("sample-pack", config=_config(), root=tmp_path)
    assert manifest.name == "sample-pack"
    assert (tmp_path / "packs" / "installed" / "sample-pack" / "pack.yaml").exists()


def test_install_unknown_pack_raises(tmp_path):
    with pytest.raises(PackInstallError, match="no pack named"):
        install_pack("does-not-exist", config=_config(), root=tmp_path)


def test_install_rejects_name_mismatch(tmp_path):
    _make_registry_pack(tmp_path, name="dir-name", contents=VALID_YAML)  # pack.yaml says sample-pack
    with pytest.raises(PackInstallError, match="does not match"):
        install_pack("dir-name", config=_config(), root=tmp_path)


def test_install_rejects_self_dependency(tmp_path):
    self_dep_yaml = VALID_YAML.replace("dependencies: []", "dependencies: [sample-pack]")
    _make_registry_pack(tmp_path, contents=self_dep_yaml)
    with pytest.raises(PackInstallError, match="itself as a dependency"):
        install_pack("sample-pack", config=_config(), root=tmp_path)


def test_install_rejects_unsafe_name_before_touching_disk(tmp_path):
    with pytest.raises(PackInstallError, match="slug"):
        install_pack("../../etc", config=_config(), root=tmp_path)


def test_install_rejects_a_missing_dependency(tmp_path):
    dep_yaml = VALID_YAML.replace("dependencies: []", "dependencies: [required-pack]")
    _make_registry_pack(tmp_path, contents=dep_yaml)
    with pytest.raises(PackInstallError, match="required-pack"):
        install_pack("sample-pack", config=_config(), root=tmp_path)
    assert not (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_install_succeeds_when_dependency_already_installed(tmp_path):
    _make_registry_pack(tmp_path, name="required-pack", contents=VALID_YAML.replace("name: sample-pack", "name: required-pack"))
    install_pack("required-pack", config=_config(), root=tmp_path)

    dep_yaml = VALID_YAML.replace("dependencies: []", "dependencies: [required-pack]")
    _make_registry_pack(tmp_path, contents=dep_yaml)
    manifest = install_pack("sample-pack", config=_config(), root=tmp_path)
    assert manifest.name == "sample-pack"
    assert (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_list_installed_returns_valid_and_invalid(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)
    broken_dir = tmp_path / "packs" / "installed" / "broken-pack"
    broken_dir.mkdir(parents=True)
    (broken_dir / "pack.yaml").write_text("name: only-a-name\n", encoding="utf-8")

    results = list_installed_packs(config=_config(), root=tmp_path)
    by_dirname = {pack_dir.name: (manifest, error) for pack_dir, manifest, error in results}

    manifest, error = by_dirname["sample-pack"]
    assert manifest is not None and error is None

    manifest, error = by_dirname["broken-pack"]
    assert manifest is None and "failed schema validation" in error


def test_list_installed_empty_when_dir_missing(tmp_path):
    results = list_installed_packs(config=_config(), root=tmp_path)
    assert results == []


def test_remove_deletes_installed_pack(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)
    removed = remove_pack("sample-pack", config=_config(), root=tmp_path)
    assert removed is True
    assert not (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_remove_returns_false_when_not_installed(tmp_path):
    removed = remove_pack("never-installed", config=_config(), root=tmp_path)
    assert removed is False


def test_install_reinstalls_over_existing_directory(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)
    installed_dir = tmp_path / "packs" / "installed" / "sample-pack"
    stale_file = installed_dir / "stale-leftover.txt"
    stale_file.write_text("should be gone after reinstall", encoding="utf-8")

    manifest = install_pack("sample-pack", config=_config(), root=tmp_path)

    assert manifest.name == "sample-pack"
    assert (installed_dir / "pack.yaml").exists()
    assert not stale_file.exists()  # reinstall replaces the directory wholesale


def test_install_failed_copy_leaves_existing_install_untouched(tmp_path, monkeypatch):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)
    installed_dir = tmp_path / "packs" / "installed" / "sample-pack"
    original_manifest_text = (installed_dir / "pack.yaml").read_text(encoding="utf-8")

    import shutil as shutil_module

    real_copytree = shutil_module.copytree

    def _flaky_copytree(src, dst, *args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(shutil_module, "copytree", _flaky_copytree)
    try:
        with pytest.raises(OSError, match="simulated copy failure"):
            install_pack("sample-pack", config=_config(), root=tmp_path)
    finally:
        monkeypatch.setattr(shutil_module, "copytree", real_copytree)

    # The original install must still be intact — a failed reinstall must
    # not have deleted it before the copy was known to succeed.
    assert installed_dir.exists()
    assert (installed_dir / "pack.yaml").read_text(encoding="utf-8") == original_manifest_text


def test_install_honors_configured_packs_registry_path(tmp_path):
    custom_registry = tmp_path / "somewhere-else" / "registry"
    pack_dir = custom_registry / "sample-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(VALID_YAML, encoding="utf-8")

    config = {
        "paths": {
            "packs_installed": "packs/installed",
            "packs_registry": str(custom_registry),
        }
    }
    manifest = install_pack("sample-pack", config=config, root=tmp_path)
    assert manifest.name == "sample-pack"
    assert (tmp_path / "packs" / "installed" / "sample-pack" / "pack.yaml").exists()


def test_list_installed_reports_malformed_yaml_without_raising(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)
    malformed_dir = tmp_path / "packs" / "installed" / "malformed-pack"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "pack.yaml").write_text(
        "name: [unbalanced\n  bad indentation:\nfoo\n", encoding="utf-8"
    )

    results = list_installed_packs(config=_config(), root=tmp_path)
    by_dirname = {pack_dir.name: (manifest, error) for pack_dir, manifest, error in results}

    manifest, error = by_dirname["malformed-pack"]
    assert manifest is None
    assert error is not None


@requires_symlinks
def test_list_installed_ignores_a_symlinked_directory(tmp_path):
    """A symlinked entry under packs/installed must not count as an
    installed pack — an installed pack is a real copy (install_pack always
    copytree's), and a symlink there could point anywhere on disk outside
    the governed install directory."""
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(), root=tmp_path)

    real_target = tmp_path / "outside-target"
    real_target.mkdir()
    (real_target / "pack.yaml").write_text(VALID_YAML.replace("sample-pack", "linked-pack"), encoding="utf-8")
    link = tmp_path / "packs" / "installed" / "linked-pack"
    os.symlink(real_target, link, target_is_directory=True)

    results = list_installed_packs(config=_config(), root=tmp_path)
    names = {pack_dir.name for pack_dir, _, _ in results}
    assert names == {"sample-pack"}


@requires_symlinks
def test_remove_unlinks_a_symlinked_install_without_deleting_the_target(tmp_path):
    """remove_pack on a symlinked packs/installed/<name> must remove just
    the symlink, not shutil.rmtree through it into whatever it points at
    (rmtree on a symlink normally raises OSError; even if it didn't, that
    would delete arbitrary content outside the governed install dir)."""
    real_target = tmp_path / "outside-target"
    real_target.mkdir()
    (real_target / "keepme.txt").write_text("do not delete", encoding="utf-8")
    link = tmp_path / "packs" / "installed" / "linked-pack"
    link.parent.mkdir(parents=True)
    os.symlink(real_target, link, target_is_directory=True)

    removed = remove_pack("linked-pack", config=_config(), root=tmp_path)
    assert removed is True
    assert not link.exists()
    assert real_target.exists()  # the symlink target itself must survive
    assert (real_target / "keepme.txt").exists()


def _install_required(tmp_path, version="1.0.0"):
    yaml = VALID_YAML.replace("name: sample-pack", "name: required-pack").replace("version: 1.0.0", f"version: {version}")
    _make_registry_pack(tmp_path, name="required-pack", contents=yaml)
    install_pack("required-pack", config=_config(), root=tmp_path)


def test_dependency_with_a_satisfied_version_range_installs(tmp_path):
    _install_required(tmp_path, "1.2.0")
    _make_registry_pack(tmp_path, contents=VALID_YAML.replace("dependencies: []", 'dependencies: ["required-pack >=1.0.0,<2.0.0"]'))
    assert install_pack("sample-pack", config=_config(), root=tmp_path).name == "sample-pack"


def test_dependency_with_an_unsatisfied_version_range_is_refused(tmp_path):
    _install_required(tmp_path, "2.1.0")
    _make_registry_pack(tmp_path, contents=VALID_YAML.replace("dependencies: []", 'dependencies: ["required-pack >=1.0.0,<2.0.0"]'))
    with pytest.raises(PackInstallError, match="required-pack 2.1.0 does not satisfy >=1.0.0,<2.0.0"):
        install_pack("sample-pack", config=_config(), root=tmp_path)
    assert not (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_malformed_dependency_entries_are_rejected_by_the_manifest(tmp_path):
    from core.packs.models import PackManifest

    base = dict(name="x-pack", version="1.0.0", kind="intelligence", summary="s", requires_core=">=0.1.0", permissions_rationale="r")
    for bad in ["Bad_Name", "ok-pack >=1.0", "ok-pack ~1.0.0", "ok-pack >=1.0.0 extra"]:
        with pytest.raises(ValueError):
            PackManifest(**base, dependencies=[bad])
    assert PackManifest(**base, dependencies=["ok-pack", "other-pack >=1.0.0,<2.0.0"]).dependency_names() == ["ok-pack", "other-pack"]


def test_removing_a_pack_another_pack_depends_on_is_refused(tmp_path):
    _install_required(tmp_path)
    _make_registry_pack(tmp_path, contents=VALID_YAML.replace("dependencies: []", "dependencies: [required-pack]"))
    install_pack("sample-pack", config=_config(), root=tmp_path)
    with pytest.raises(PackInstallError, match="sample-pack depends on it"):
        remove_pack("required-pack", config=_config(), root=tmp_path)
    remove_pack("sample-pack", config=_config(), root=tmp_path)
    remove_pack("required-pack", config=_config(), root=tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_a_junction_in_installed_is_not_a_pack_and_removal_unlinks_only_the_junction(tmp_path):
    import subprocess

    target = tmp_path / "target"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    installed = tmp_path / "packs" / "installed"
    installed.mkdir(parents=True)
    link = installed / "evil-pack"
    assert subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    assert [p.name for p, _, _ in list_installed_packs(config=_config(), root=tmp_path)] == []
    assert remove_pack("evil-pack", config=_config(), root=tmp_path) is True
    assert not link.exists() and (target / "precious.txt").exists()
