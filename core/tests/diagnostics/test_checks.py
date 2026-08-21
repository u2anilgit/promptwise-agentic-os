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
