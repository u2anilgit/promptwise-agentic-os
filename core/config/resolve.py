# core/config/resolve.py
"""Layered config resolution — docs/ARCHITECTURE.md §4.

Precedence, later wins: system defaults < org config < project config <
user local overrides < environment variables. System defaults are the only
layer that is not optional — a missing defaults.yaml means the package
install itself is broken, so it raises instead of silently returning {}.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
ENV_PREFIX = "PROMPTWISE_"

# Conventional on-disk locations, ARCHITECTURE.md §4 rows 2-4.
ORG_CONFIG_FILENAME = "promptwise.config.yaml"
PROJECT_CONFIG_RELPATH = Path(".promptwise") / "config.yaml"
LOCAL_CONFIG_RELPATH = Path(".promptwise") / "local.yaml"


def _load_defaults() -> dict[str, Any]:
    if not DEFAULTS_PATH.exists():
        raise FileNotFoundError(
            f"system defaults config missing at {DEFAULTS_PATH} — package installation is broken"
        )
    with DEFAULTS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_scalar(raw: str) -> Any:
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """PROMPTWISE_ENGINE__LOCAL_ONLY=true -> {"engine": {"local_only": True}}"""
    result: dict[str, Any] = {}
    for key, raw_value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX):].lower().split("__")
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce_scalar(raw_value)
    return result


def resolve_config(
    org_path: Path | None = None,
    project_path: Path | None = None,
    local_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cfg = _load_defaults()
    for path in (org_path, project_path, local_path):
        cfg = _deep_merge(cfg, _load_yaml(path))
    cfg = _deep_merge(cfg, _env_overrides(env if env is not None else os.environ))
    return cfg


def discover_config_paths(root: Path | None = None) -> tuple[Path, Path, Path]:
    """Conventional org/project/local config locations under `root` (default cwd)."""
    root = root if root is not None else Path.cwd()
    return (
        root / ORG_CONFIG_FILENAME,
        root / PROJECT_CONFIG_RELPATH,
        root / LOCAL_CONFIG_RELPATH,
    )


def resolve_config_auto(
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """resolve_config(), but discovering org/project/local paths at their
    conventional locations instead of requiring the caller to pass them.
    This is the entry point every other core module should use — the
    explicit-path form of resolve_config() stays for tests and for callers
    that genuinely have a non-standard layout.
    """
    org_path, project_path, local_path = discover_config_paths(root)
    return resolve_config(org_path, project_path, local_path, env)
