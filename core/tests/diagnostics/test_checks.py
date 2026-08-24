# core/tests/diagnostics/test_checks.py
from core.diagnostics.checks import run_diagnostics


def test_run_diagnostics_returns_all_check_names():
    results = run_diagnostics()
    names = {r.name for r in results}
    assert names == {
        "hardware.ram",
        "config.resolve",
        "packs.integrity",
        "services.ollama",
        "services.qdrant",
        "policy.load",
        "audit.chain",
        "services.gateway",
    }


def test_hardware_ram_check_passes_on_a_real_machine():
    results = run_diagnostics()
    ram_check = next(r for r in results if r.name == "hardware.ram")
    assert ram_check.status in ("PASS", "WARN")  # WARN only if <4GB available


def test_config_resolve_check_passes_with_defaults():
    results = run_diagnostics()
    config_check = next(r for r in results if r.name == "config.resolve")
    assert config_check.status == "PASS"


def test_packs_integrity_passes_with_zero_packs():
    results = run_diagnostics()
    packs_check = next(r for r in results if r.name == "packs.integrity")
    assert packs_check.status == "PASS"
    assert "0 packs" in packs_check.message


def test_unimplemented_checks_warn_not_fail():
    results = run_diagnostics()
    for name in ("services.ollama", "services.qdrant", "policy.load", "audit.chain"):
        check = next(r for r in results if r.name == name)
        assert check.status == "WARN"


def test_no_failures_means_clean_exit():
    results = run_diagnostics()
    assert not any(r.status == "FAIL" for r in results)


def test_services_gateway_check_never_fails_or_raises():
    results = run_diagnostics()
    gateway_check = next(r for r in results if r.name == "services.gateway")
    assert gateway_check.status in ("PASS", "WARN")


def test_config_resolve_check_reports_which_root_it_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.diagnostics.checks import run_diagnostics

    results = run_diagnostics()
    config_check = next(r for r in results if r.name == "config.resolve")
    assert config_check.status == "PASS"
    assert str(tmp_path) in config_check.message


_EXAMPLE_PACK_MANIFEST = (
    "name: example-pack\n"
    "version: 1.0.0\n"
    "kind: intelligence\n"
    "summary: test\n"
    'requires_core: ">=0.0.0,<1.0.0"\n'
    "permissions_rationale: none needed\n"
)


def test_packs_integrity_uses_configured_path(tmp_path, monkeypatch):
    from core.diagnostics.checks import _check_packs_integrity

    packs_dir = tmp_path / "custom_packs"
    pack_dir = packs_dir / "example-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(_EXAMPLE_PACK_MANIFEST, encoding="utf-8")
    config = {"paths": {"packs_installed": str(packs_dir)}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "1 pack" in result.message


def test_packs_integrity_passes_when_directory_does_not_exist(tmp_path):
    # list_installed_packs treats a missing install dir as zero packs, not
    # an error — real manifest validation (this task) only fires per-pack.
    from core.diagnostics.checks import _check_packs_integrity

    missing_dir = tmp_path / "no-such-packs-dir"
    config = {"paths": {"packs_installed": str(missing_dir)}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "0 packs" in result.message


def test_packs_integrity_resolves_relative_configured_path_against_root(tmp_path, monkeypatch):
    from core.diagnostics.checks import _check_packs_integrity

    monkeypatch.chdir(tmp_path)
    pack_dir = tmp_path / "packs" / "installed" / "example-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(_EXAMPLE_PACK_MANIFEST, encoding="utf-8")
    config = {"paths": {"packs_installed": "packs/installed"}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "1 pack" in result.message


def test_packs_integrity_passes_with_zero_packs_direct(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "0 packs" in result.message


def test_packs_integrity_zero_packs_message_includes_resolved_path(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    installed_dir = tmp_path / "packs" / "installed"
    config = {"paths": {"packs_installed": str(installed_dir)}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert str(installed_dir) in result.message


def test_packs_integrity_passes_with_one_valid_pack(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    pack_dir = tmp_path / "packs" / "installed" / "sample-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: sample-pack\n"
        "version: 1.0.0\n"
        "kind: intelligence\n"
        "summary: test\n"
        'requires_core: ">=0.0.0,<1.0.0"\n'
        "permissions_rationale: none needed\n",
        encoding="utf-8",
    )
    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "1 pack" in result.message


def test_packs_integrity_fails_with_invalid_manifest(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    pack_dir = tmp_path / "packs" / "installed" / "broken-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text("name: only-a-name\n", encoding="utf-8")
    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "FAIL"
    assert "broken-pack" in result.message
