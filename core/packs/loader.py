"""Pack manifest loading + validation — docs/ARCHITECTURE.md §3, step 2 of
the install/discovery mechanism ("validates pack.yaml against the manifest
schema, checks requires_core semver range").

Capability *enforcement* (registering with check_policy) is explicit Phase 3
scope and does NOT happen here — this module only parses and validates the
declared capabilities list. See PackManifest.capabilities.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

import core
from core.packs.models import PackManifest
from core.packs.semver import InvalidVersionError, satisfies


class PackValidationError(ValueError):
    """Raised when a pack.yaml fails schema, parsing, or semver validation."""


def load_pack_manifest(pack_dir: Path, core_version: str | None = None) -> PackManifest:
    core_version = core_version if core_version is not None else core.__version__
    manifest_path = pack_dir / "pack.yaml"
    if not manifest_path.exists():
        raise PackValidationError(f"{pack_dir} has no pack.yaml")

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        raise PackValidationError(f"{manifest_path} could not be read/parsed: {exc}") from exc

    try:
        manifest = PackManifest.model_validate(raw)
    except ValidationError as exc:
        raise PackValidationError(f"{manifest_path} failed schema validation: {exc}") from exc

    try:
        in_range = satisfies(core_version, manifest.requires_core)
    except InvalidVersionError as exc:
        raise PackValidationError(
            f"{manifest_path} has an invalid requires_core range {manifest.requires_core!r}: {exc}"
        ) from exc

    if not in_range:
        raise PackValidationError(
            f"{manifest.name} requires_core {manifest.requires_core!r}, "
            f"but the running core is {core_version}"
        )

    return manifest
