# core/routing/catalog.py
"""Model catalog loader — docs/research/aug2026-findings.md Part 5 row 5.

Reads catalog/model_catalog.yaml through config (never a raw hardcoded
path), same pattern Task 2 established for packs/installed. Path resolution
goes through core.config.resolve.resolve_path so a relative configured path
is anchored to the discovered config root, not the process's CWD.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.config.resolve import resolve_config_auto, resolve_path
from core.routing.models import ModelTier

# Packaged fallback copy of the catalog, used only when the resolved
# configured/default path doesn't exist on disk (e.g. a pip install running
# outside a repo checkout). catalog/model_catalog.yaml at the repo root
# stays the canonical, editable copy.
_PACKAGED_CATALOG_PATH = Path(__file__).parent / "model_catalog.yaml"


def _catalog_path(config: dict[str, Any] | None, root: Path | None = None) -> Path:
    config = config if config is not None else resolve_config_auto()
    return resolve_path(config, "paths.model_catalog", "catalog/model_catalog.yaml", root=root)


def load_catalog(config: dict[str, Any] | None = None) -> dict[str, ModelTier]:
    path = _catalog_path(config)
    if not path.exists():
        path = _PACKAGED_CATALOG_PATH
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    tiers = raw.get("tiers", {})
    return {name: ModelTier(name=name, **fields) for name, fields in tiers.items()}


def tier_order(catalog: dict[str, ModelTier]) -> list[str]:
    """Ascending cost/size order: local tiers before cloud, cheaper/smaller
    before pricier/bigger within each group — derived from catalog data so
    an operator can add a tier without touching core (root CLAUDE.md goal 2).
    """
    return sorted(
        catalog.keys(),
        key=lambda name: (
            catalog[name].requires_cloud,
            catalog[name].min_ram_gb,
            catalog[name].cost_per_1k_input_usd,
        ),
    )
