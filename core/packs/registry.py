"""Pack install/list/remove — docs/ARCHITECTURE.md §3 install/discovery
mechanism. Deliberately stateless: every call re-scans disk, so there is no
in-memory registry cache to invalidate on change. That satisfies "packs are
hot-discoverable ... no core restart required for content-only packs"
without a filesystem watcher (YAGNI — nothing in this repo yet holds a
long-lived pack registry in memory across calls).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

from core.config.resolve import resolve_config_auto, resolve_path
from core.packs.loader import PackValidationError, load_pack_manifest
from core.packs.models import PACK_NAME_RE, PackManifest

REGISTRY_DIRNAME = "registry"


class PackInstallError(ValueError):
    """Raised when installing or resolving a pack fails."""


def _validate_name(name: str) -> None:
    if not PACK_NAME_RE.match(name):
        raise PackInstallError(
            f"pack name {name!r} must be a lowercase slug matching {PACK_NAME_RE.pattern}"
        )


def _installed_dir(config: dict | None, root: Path | None) -> Path:
    resolved_root = root if root is not None else Path.cwd()
    config = config if config is not None else resolve_config_auto(root=resolved_root)
    return resolve_path(config, "paths.packs_installed", "packs/installed", root=resolved_root)


def _registry_dir(config: dict | None, root: Path | None) -> Path:
    resolved_root = root if root is not None else Path.cwd()
    config = config if config is not None else resolve_config_auto(root=resolved_root)
    return resolve_path(config, "paths.packs_registry", f"packs/{REGISTRY_DIRNAME}", root=resolved_root)


def list_installed_packs(
    config: dict | None = None, root: Path | None = None
) -> list[tuple[Path, PackManifest | None, str | None]]:
    """One (pack_dir, manifest, error) tuple per installed pack directory.
    Invalid packs are reported via the error slot, never raised — matches
    doctor's never-crash convention (core/diagnostics/checks.py). A
    syntactically malformed pack.yaml raises yaml.YAMLError rather than
    PackValidationError (load_pack_manifest does not wrap parse errors), so
    both are caught here."""
    installed_dir = _installed_dir(config, root)
    if not installed_dir.exists():
        return []
    results: list[tuple[Path, PackManifest | None, str | None]] = []
    for pack_dir in sorted(p for p in installed_dir.iterdir() if p.is_dir()):
        try:
            manifest = load_pack_manifest(pack_dir)
            results.append((pack_dir, manifest, None))
        except (PackValidationError, yaml.YAMLError) as exc:
            results.append((pack_dir, None, str(exc)))
    return results


def install_pack(name: str, config: dict | None = None, root: Path | None = None) -> PackManifest:
    _validate_name(name)  # before any path is built or touched
    resolved_root = root if root is not None else Path.cwd()
    registry_dir = _registry_dir(config, resolved_root)
    source_dir = registry_dir / name
    if not source_dir.exists():
        raise PackInstallError(f"no pack named {name!r} in {registry_dir}")

    manifest = load_pack_manifest(source_dir)  # validate BEFORE copying anything
    if manifest.name != name:
        raise PackInstallError(
            f"pack.yaml name {manifest.name!r} does not match requested pack {name!r}"
        )
    if manifest.name in manifest.dependencies:
        raise PackInstallError(f"{name} declares itself as a dependency")

    installed_dir = _installed_dir(config, resolved_root)
    dest_dir = installed_dir / name
    # Defense in depth beyond the slug regex: the resolved dest must stay
    # inside installed_dir even after path resolution.
    installed_dir.mkdir(parents=True, exist_ok=True)
    if installed_dir.resolve() not in dest_dir.resolve().parents and dest_dir.resolve() != installed_dir.resolve():
        raise PackInstallError(f"resolved install path {dest_dir} escapes {installed_dir}")

    # Copy into a sibling temp dir first, then swap it into place — a copy
    # failure (partway through a large pack, a permissions error, disk
    # full) leaves any existing install untouched instead of deleting it
    # before the replacement is known to be complete.
    temp_dir = Path(tempfile.mkdtemp(dir=installed_dir, prefix=f".{name}.tmp-"))
    temp_dir.rmdir()  # mkdtemp creates it; copytree requires the dest not to exist yet
    try:
        shutil.copytree(source_dir, temp_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    temp_dir.rename(dest_dir)
    return manifest


def remove_pack(name: str, config: dict | None = None, root: Path | None = None) -> bool:
    _validate_name(name)
    dest_dir = _installed_dir(config, root) / name
    if not dest_dir.exists():
        return False
    shutil.rmtree(dest_dir)
    return True
