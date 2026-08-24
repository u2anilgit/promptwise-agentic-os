"""Pack manifest schema — docs/ARCHITECTURE.md §3 "pack.yaml (required
fields)". This is the typed contract every pack.yaml is validated against;
breaking it is a semver-major event (core/CLAUDE.md conventions).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator

from core.packs.semver import InvalidVersionError, parse_version

PackKind = Literal[
    "stack",
    "database",
    "cloud-devops",
    "architecture",
    "migration",
    "lifecycle",
    "intelligence",
]

# Pack names become directory names under packs/installed/<name> — must be a
# safe slug so a malicious or malformed name can never escape that directory
# (e.g. "../../etc") when registry.py builds filesystem paths from it.
PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PackManifest(BaseModel):
    name: str
    version: str
    kind: PackKind
    summary: str
    requires_core: str
    capabilities: list[str] = []
    permissions_rationale: str
    dependencies: list[str] = []

    @field_validator("name")
    @classmethod
    def _name_is_safe_slug(cls, v: str) -> str:
        if not PACK_NAME_RE.match(v):
            raise ValueError(
                f"pack name {v!r} must be a lowercase slug matching {PACK_NAME_RE.pattern} "
                "(letters, digits, hyphens only, starting with a letter or digit)"
            )
        return v

    @field_validator("version")
    @classmethod
    def _version_is_valid_semver(cls, v: str) -> str:
        try:
            parse_version(v)
        except InvalidVersionError as exc:
            raise ValueError(f"pack version {v!r} is not a valid X.Y.Z version: {exc}") from exc
        return v

    @field_validator("permissions_rationale")
    @classmethod
    def _rationale_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("permissions_rationale must not be blank — ARCHITECTURE.md §3 requires it")
        return v
