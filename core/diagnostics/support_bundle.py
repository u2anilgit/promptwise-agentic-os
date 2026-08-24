"""generate_support_bundle — docs/MAINTENANCE.md §3. Collects doctor
output, the resolved config (redacted), and the audit trail tail into one
shareable zip. Log collection (per-pack structured logs) is a no-op for
now — no pack system exists yet (Phase 8); the bundle collects what this
phase's subsystems actually produce.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import yaml

from core.diagnostics.checks import run_diagnostics
from core.diagnostics.redact import redact_secrets


def _doctor_output_text(config: dict[str, Any]) -> str:
    results = run_diagnostics(config)
    lines = [f"[{r.status}] {r.name} — {r.message}" for r in results]
    return "\n".join(lines)


def _resolved_config_text(config: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(config, sort_keys=True)
    return redact_secrets(dumped)


def _audit_tail_text(config: dict[str, Any], max_lines: int = 200) -> str:
    from core.config.resolve import resolve_path

    path = resolve_path(config, "audit.log_path", ".promptwise/audit.jsonl")
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = "".join(lines[-max_lines:])
    return redact_secrets(tail)


def generate_support_bundle(config: dict[str, Any], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doctor_output.txt", _doctor_output_text(config))
        z.writestr("resolved_config.yaml", _resolved_config_text(config))
        z.writestr("audit_tail.jsonl", _audit_tail_text(config))

    return out_path
