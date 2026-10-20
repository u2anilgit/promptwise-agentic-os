# core/diagnostics/checks.py
"""promptwise doctor — core health checks. docs/MAINTENANCE.md §2."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from core.config.resolve import resolve_config, resolve_config_auto, resolve_path
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
    # Local import: keeps core/packs/ import cost (pydantic, yaml) out of
    # this module's load path for callers that never run doctor's packs
    # check — not needed to avoid a cycle, there isn't one.
    from core.packs.registry import list_installed_packs

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
    if count == 0:
        installed_dir = resolve_path(config, "paths.packs_installed", "packs/installed")
        return CheckResult(
            name="packs.integrity",
            status="PASS",
            message=f"0 packs installed ({installed_dir} — normal before first `pack install`)",
        )
    noun = "pack" if count == 1 else "packs"
    return CheckResult(name="packs.integrity", status="PASS", message=f"{count} {noun} installed, all valid")


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


def _check_policy_load(config: dict | None = None) -> CheckResult:
    from core.policy.engine import load_policy

    config = config if config is not None else resolve_config_auto()
    try:
        rules = load_policy(config)
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad policy file
        return CheckResult(name="policy.load", status="FAIL", message=f"policy failed to load: {exc}")
    return CheckResult(name="policy.load", status="PASS", message=f"{len(rules)} rule(s) loaded")


def _check_audit_chain(config: dict | None = None) -> CheckResult:
    from core.audit.log import verify_chain

    config = config if config is not None else resolve_config_auto()
    ok, broken_at = verify_chain(config)
    if ok:
        return CheckResult(name="audit.chain", status="PASS", message="hash chain unbroken")
    return CheckResult(
        name="audit.chain",
        status="FAIL",
        message=f"hash chain broken at record index {broken_at} — audit log may have been tampered with",
    )


def _check_db_schema(config: dict) -> CheckResult:
    from core.db.migrate import current_revision, head_revision, known_revisions

    try:
        current = current_revision(config)
        head = head_revision()
        if current is None:
            return CheckResult(name="db.schema", status="WARN", message="database not created yet — run `promptwise db upgrade`")
        if current not in known_revisions():
            return CheckResult(name="db.schema", status="FAIL", message=f"database revision {current} is newer than this code (head {head}) — upgrade the code, do not downgrade the data")
        if current != head:
            return CheckResult(name="db.schema", status="WARN", message=f"database at {current}, code expects {head} — run `promptwise db upgrade`")
        return CheckResult(name="db.schema", status="PASS", message=f"schema at head ({head})")
    except Exception as exc:  # noqa: BLE001 — doctor must never crash
        return CheckResult(name="db.schema", status="WARN", message=f"schema check could not complete: {exc}")


def _check_deps_integrity(config: dict) -> CheckResult:
    from core.security.supply_chain import check_dependencies

    return check_dependencies(config)


def _http_get(base: str, path: str) -> bytes | None:
    """GET a local service endpoint; None when unreachable. Only http(s) URLs are probed."""
    if not isinstance(base, str) or not base.startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=1) as response:  # noqa: S310 - scheme checked above
            return response.read(1_000_000) if response.status == 200 else None
    except Exception:  # noqa: BLE001 - doctor must never crash; unreachable is a valid state
        return None


def _check_services_ollama(config: dict) -> CheckResult:
    memory = config.get("memory", {})
    base = memory.get("ollama_base_url", "http://127.0.0.1:11434")
    body = _http_get(base, "/api/tags")
    if body is None:
        return CheckResult(name="services.ollama", status="WARN", message=f"Ollama not reachable at {base} - local models and memory embeddings are unavailable until it runs")
    try:
        names = [m["name"] for m in json.loads(body)["models"]]
    except (ValueError, KeyError, TypeError):
        return CheckResult(name="services.ollama", status="WARN", message=f"{base}/api/tags did not return an Ollama model list")
    embedding = memory.get("embedding_model", "nomic-embed-text")
    if not any(n == embedding or n.split(":")[0] == embedding for n in names):
        return CheckResult(name="services.ollama", status="WARN", message=f"Ollama reachable ({len(names)} model(s)) but embedding model '{embedding}' is missing - run `ollama pull {embedding}`")
    return CheckResult(name="services.ollama", status="PASS", message=f"Ollama reachable at {base}, {len(names)} model(s) available")


def _check_services_qdrant(config: dict) -> CheckResult:
    base = config.get("memory", {}).get("qdrant_url", "http://127.0.0.1:6333")
    if _http_get(base, "/readyz") is None:
        return CheckResult(name="services.qdrant", status="WARN", message=f"Qdrant not reachable at {base} - memory recall falls back to full-text search")
    return CheckResult(name="services.qdrant", status="PASS", message=f"Qdrant ready at {base}")


# Operator-owned governance files: (label, dotted config key, default path).
_GOVERNANCE_FILES = (
    ("audit log", "audit.log_path", ".promptwise/agentic_audit.jsonl"),
    ("policies", "paths.policies_dir", "policies"),
    ("tool registry", "policy.tool_registry_path", "tool_registry.yaml"),
    ("JIT grants", "policy.jit_grants_path", ".promptwise/jit_grants.json"),
    ("database", "database.path", ".promptwise/agentic.sqlite3"),
    ("model catalog", "paths.model_catalog", "catalog/model_catalog.yaml"),
    ("API credential", "gateway.token_path", "~/.promptwise/dashboard_token"),
)


def _check_governance_exposure(config: dict) -> CheckResult:
    """WARN when governance files resolve inside a root agents may write (gateway.allowed_roots, default
    the cwd). Fine for a single-developer setup protected by git review; a hardened deployment relocates
    them via the operator config (gateway/CLAUDE.md, Operator config)."""
    operator_file = os.environ.get("PROMPTWISE_OPERATOR_CONFIG")
    if operator_file:  # judge what the gateway actually uses, not the agent-writable project layers
        config = resolve_config(org_path=Path(operator_file), project_path=None, local_path=None, env=os.environ)
    # Same resolution as gateway/mcp_guard.py allowed_roots().
    roots = [Path(r).resolve() for r in (config.get("gateway", {}).get("allowed_roots") or [])] or [Path.cwd().resolve()]
    exposed = []
    for label, key, default in _GOVERNANCE_FILES:
        node = config
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        raw = node if isinstance(node, str) and node else default
        path = Path(raw).expanduser()
        path = (path if path.is_absolute() else Path.cwd() / path).resolve()
        if any(path == r or r in path.parents for r in roots):
            exposed.append(label)
    if exposed:
        return CheckResult(
            name="governance.exposure", status="WARN",
            message=f"inside an agent-writable root: {', '.join(exposed)} - acceptable for a single-developer setup under git review; relocate via PROMPTWISE_OPERATOR_CONFIG for a hardened deployment",
        )
    return CheckResult(name="governance.exposure", status="PASS", message="governance files are outside the agent-writable roots")


def run_diagnostics(config: dict | None = None) -> list[CheckResult]:
    config = config if config is not None else resolve_config_auto()
    return [
        _check_hardware_ram(),
        _check_config_resolve(),
        _check_packs_integrity(config),
        _check_services_ollama(config),
        _check_services_qdrant(config),
        _check_policy_load(config),
        _check_audit_chain(config),
        _check_services_gateway(config),
        _check_deps_integrity(config),
        _check_db_schema(config),
        _check_governance_exposure(config),
    ]
