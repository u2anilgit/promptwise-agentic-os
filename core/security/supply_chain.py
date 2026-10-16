# core/security/supply_chain.py
"""Dependency supply-chain checks — docs/research/2026-10-16-agent-landscape-gap-analysis.md
pain point 1 (e.g. the LiteLLM 1.82.7/1.82.8 PyPI compromise of 2026-03-24).

Two independent signals, both data-driven so an org updates them without
touching core:
  * a known-bad deny-list (YAML, `security.known_bad_packages_path`):
    an installed package/version on it is a FAIL;
  * a hash-pinned lockfile (`security.lockfile_path`, pip `--hash` format,
    e.g. `uv pip compile --generate-hashes`): pin drift or an unhashed
    entry is a WARN, a missing lockfile is a WARN.
Never raises — doctor must report, not crash.
"""
from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

import yaml
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ValidationError

from core.config.resolve import resolve_path
from core.diagnostics.models import CheckResult

DEFAULT_KNOWN_BAD_PATH = "security/known_bad_packages.yaml"
DEFAULT_LOCKFILE_PATH = "requirements.lock"


class BadPackage(BaseModel):
    package: str
    versions: list[str]
    reason: str = ""
    reference: str = ""


class BadHit(BaseModel):
    package: str
    installed_version: str
    reason: str = ""
    reference: str = ""


class LockEntry(BaseModel):
    name: str
    version: str
    hashes: list[str] = []


def installed_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            out[str(canonicalize_name(name))] = dist.version
    return out


def load_known_bad(config: dict[str, Any]) -> list[BadPackage]:
    path = resolve_path(config, "security.known_bad_packages_path", DEFAULT_KNOWN_BAD_PATH)
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = [BadPackage.model_validate(item) for item in raw.get("packages", [])]
    except (yaml.YAMLError, ValidationError, OSError, UnicodeDecodeError, AttributeError):
        return []
    return [e.model_copy(update={"package": str(canonicalize_name(e.package))}) for e in entries]


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def find_known_bad(installed: Mapping[str, str], known_bad: list[BadPackage]) -> list[BadHit]:
    normalized: dict[str, str] = {str(canonicalize_name(k)): v for k, v in installed.items()}
    hits: list[BadHit] = []
    for entry in known_bad:
        version = normalized.get(entry.package)
        if version is not None and any(_same_version(version, bad) for bad in entry.versions):
            hits.append(BadHit(package=entry.package, installed_version=version, reason=entry.reason, reference=entry.reference))
    return hits


_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;\\]+)")
_HASH = re.compile(r"--hash=(sha256:[0-9a-fA-F]{64})")


def parse_lockfile(path: Path) -> list[LockEntry]:
    entries: list[LockEntry] = []
    current: LockEntry | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pin = _PIN.match(line) if not stripped.startswith("--") else None
        if pin:
            current = LockEntry(name=str(canonicalize_name(pin.group(1))), version=pin.group(2))
            entries.append(current)
        if current is not None:
            current.hashes.extend(_HASH.findall(line))
    return entries


def check_dependencies(config: dict[str, Any], installed: Mapping[str, str] | None = None) -> CheckResult:
    try:
        return _check(config, installed)
    except Exception as exc:  # noqa: BLE001 — doctor must never crash
        return CheckResult(name="deps.integrity", status="WARN", message=f"dependency check could not complete: {exc}")


def _check(config: dict[str, Any], installed: Mapping[str, str] | None) -> CheckResult:
    installed = {str(canonicalize_name(k)): v for k, v in (installed if installed is not None else installed_versions()).items()}

    hits = find_known_bad(installed, load_known_bad(config))
    if hits:
        detail = "; ".join(f"{h.package}=={h.installed_version} ({h.reason or 'known-bad'})" for h in hits)
        return CheckResult(name="deps.integrity", status="FAIL", message=f"known-bad package(s) installed — {detail}. Uninstall and rotate any credentials present in that environment.")

    lock_path = resolve_path(config, "security.lockfile_path", DEFAULT_LOCKFILE_PATH)
    if not lock_path.is_file():
        return CheckResult(name="deps.integrity", status="WARN", message=f"no lockfile at {lock_path} — dependencies are not hash-pinned (generate with `uv pip compile --generate-hashes`)")

    problems: list[str] = []
    for entry in parse_lockfile(lock_path):
        if not entry.hashes:
            problems.append(f"{entry.name} has no hash in lockfile")
        have = installed.get(entry.name)
        if have is not None and not _same_version(have, entry.version):
            problems.append(f"{entry.name} installed {have} != locked {entry.version}")
    if problems:
        return CheckResult(name="deps.integrity", status="WARN", message="; ".join(problems))
    return CheckResult(name="deps.integrity", status="PASS", message="no known-bad packages; lockfile pins match and are hashed")
