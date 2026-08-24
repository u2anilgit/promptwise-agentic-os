# core/diagnostics/checks.py
"""promptwise doctor — core health checks. docs/MAINTENANCE.md §2."""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from core.config.resolve import resolve_config_auto
from core.diagnostics.hardware import detect_hardware
from core.diagnostics.models import CheckResult

MIN_AVAILABLE_RAM_GB = 4.0


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
    root = Path.cwd()
    try:
        cfg = resolve_config_auto(root=root)
        assert cfg["engine"]["name"]
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad config
        return CheckResult(name="config.resolve", status="FAIL", message=f"config failed to resolve: {exc}")
    return CheckResult(
        name="config.resolve",
        status="PASS",
        message=f"all config layers merged cleanly (org/project/local discovered under {root})",
    )


def _check_packs_integrity(config: dict | None = None) -> CheckResult:
    from core.packs.registry import list_installed_packs  # local import: avoids a diagnostics->packs->config import cycle at module load time

    config = config if config is not None else resolve_config_auto()
    results = list_installed_packs(config=config)
    invalid = [(pack_dir, error) for pack_dir, manifest, error in results if error is not None]
    if invalid:
        details = "; ".join(f"{pack_dir.name}: {error}" for pack_dir, error in invalid)
        return CheckResult(
            name="packs.integrity",
            status="FAIL",
            message=f"{len(invalid)} of {len(results)} installed packs failed validation — {details}",
        )
    count = len(results)
    noun = "pack" if count == 1 else "packs"
    return CheckResult(name="packs.integrity", status="PASS", message=f"{count} {noun} installed, all valid")


def _not_yet_implemented(name: str, phase: str) -> CheckResult:
    return CheckResult(name=name, status="WARN", message=f"not yet implemented — lands in {phase}")


def _check_services_gateway(config: dict | None = None) -> CheckResult:
    config = config if config is not None else resolve_config_auto()
    port = config.get("gateway", {}).get("port", 8000)
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310 — local-only, fixed scheme
            if response.status == 200:
                return CheckResult(name="services.gateway", status="PASS", message=f"gateway reachable at 127.0.0.1:{port}")
            return CheckResult(
                name="services.gateway",
                status="WARN",
                message=f"gateway at 127.0.0.1:{port} returned status {response.status}",
            )
    except Exception:  # noqa: BLE001 — doctor must never crash; unreachable is a normal, valid state
        return CheckResult(
            name="services.gateway",
            status="WARN",
            message=f"gateway not reachable at 127.0.0.1:{port} — normal if not yet started",
        )


def run_diagnostics(config: dict | None = None) -> list[CheckResult]:
    config = config if config is not None else resolve_config_auto()
    return [
        _check_hardware_ram(),
        _check_config_resolve(),
        _check_packs_integrity(config),
        _not_yet_implemented("services.ollama", "Phase 1"),
        _not_yet_implemented("services.qdrant", "Phase 4"),
        _not_yet_implemented("policy.load", "Phase 3"),
        _not_yet_implemented("audit.chain", "Phase 3"),
        _check_services_gateway(config),
    ]
