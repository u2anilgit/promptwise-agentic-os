"""End-to-end: install a fixture pack from a copied registry dir, confirm
doctor reports it, then remove it. Exercises Tasks 1-6 together instead of
each module in isolation."""
import shutil
from pathlib import Path

from core.diagnostics.checks import _check_packs_integrity
from core.packs.registry import install_pack, list_installed_packs, remove_pack

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _seed_registry(tmp_path: Path, fixture_name: str, install_as: str) -> None:
    dest = tmp_path / "packs" / "registry" / install_as
    shutil.copytree(FIXTURES_DIR / fixture_name, dest)


def _config(tmp_path: Path) -> dict:
    return {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}


def test_valid_fixture_pack_installs_lists_and_passes_doctor(tmp_path):
    _seed_registry(tmp_path, "valid-intelligence-pack", "valid-intelligence-pack")
    config = _config(tmp_path)

    manifest = install_pack("valid-intelligence-pack", config=config, root=tmp_path)
    assert manifest.kind == "intelligence"

    results = list_installed_packs(config=config, root=tmp_path)
    assert len(results) == 1
    assert results[0][1].name == "valid-intelligence-pack"

    doctor_result = _check_packs_integrity(config)
    assert doctor_result.status == "PASS"

    removed = remove_pack("valid-intelligence-pack", config=config, root=tmp_path)
    assert removed is True
    assert list_installed_packs(config=config, root=tmp_path) == []


def test_invalid_fixture_pack_fails_doctor_after_manual_placement(tmp_path):
    # Simulate a pack that landed in packs/installed/ some other way (e.g. a
    # hand-edited manifest) rather than via install_pack, to prove doctor
    # catches it independent of the install path.
    installed_dir = tmp_path / "packs" / "installed" / "invalid-pack"
    shutil.copytree(FIXTURES_DIR / "invalid-pack", installed_dir)
    config = _config(tmp_path)

    doctor_result = _check_packs_integrity(config)
    assert doctor_result.status == "FAIL"
    assert "invalid-pack" in doctor_result.message
