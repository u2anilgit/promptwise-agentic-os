# core/diagnostics/checks.py
"""promptwise doctor — core health checks. docs/MAINTENANCE.md §2."""
from __future__ import annotations

from pathlib import Path

from core.config.resolve import resolve_config
from core.diagnostics.hardware import detect_hardware
from core.diagnostics.models import CheckResult

MIN_AVAILABLE_RAM_GB = 4.0
PACKS_INSTALLED_DIR = Path("packs/installed")


def _check_hardware_ram() -> CheckResult:
    profile = detect_hardware()
    if profile.available_ram_gb == 0.0:
        return CheckResult(
            name="hardware.ram",
            status="WARN",
            message="could not detect available RAM on this platform — routing will assume local-small tier only",
        )
    if profile.available_ram_gb < MIN_AVAILABLE_RAM_GB:
        return CheckResult(
            name="hardware.ram",
            status="WARN",
            message=f"{profile.available_ram_gb}GB free, below the {MIN_AVAILABLE_RAM_GB}GB local-small floor — cloud-cheap tier will be preferred",
        )
    return CheckResult(
        name="hardware.ram",
        status="PASS",
        message=f"{profile.available_ram_gb}GB available of {profile.total_ram_gb}GB total",
    )


def _check_config_resolve() -> CheckResult:
    try:
        cfg = resolve_config()
        assert cfg["engine"]["name"]
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad config
        return CheckResult(name="config.resolve", status="FAIL", message=f"config failed to resolve: {exc}")
    return CheckResult(name="config.resolve", status="PASS", message="all config layers merged cleanly")


def _check_packs_integrity() -> CheckResult:
    if not PACKS_INSTALLED_DIR.exists():
        return CheckResult(name="packs.integrity", status="PASS", message="0 packs installed")
    pack_dirs = [p for p in PACKS_INSTALLED_DIR.iterdir() if p.is_dir()]
    # Phase 8 adds real manifest validation here; Phase 0 only counts.
    return CheckResult(name="packs.integrity", status="PASS", message=f"{len(pack_dirs)} packs installed")


def _not_yet_implemented(name: str, phase: str) -> CheckResult:
    return CheckResult(name=name, status="WARN", message=f"not yet implemented — lands in {phase}")


def run_diagnostics(config: dict | None = None) -> list[CheckResult]:
    return [
        _check_hardware_ram(),
        _check_config_resolve(),
        _check_packs_integrity(),
        _not_yet_implemented("services.ollama", "Phase 1"),
        _not_yet_implemented("services.qdrant", "Phase 4"),
        _not_yet_implemented("policy.load", "Phase 3"),
        _not_yet_implemented("audit.chain", "Phase 3"),
    ]
