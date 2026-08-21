# core/routing/catalog.py
"""Model catalog loader — docs/research/aug2026-findings.md Part 5 row 5.

Reads catalog/model_catalog.yaml through config (never a raw hardcoded
path), same pattern Task 2 established for packs/installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.config.resolve import resolve_config_auto
from core.routing.models import ModelTier

# Ascending cost/size within each track (local, then cloud) — route_request
# walks this order to find the cheapest tier that fits.
TIER_ORDER: list[str] = ["local-small", "local-large", "cloud-cheap", "cloud-premium"]


def _catalog_path(config: dict[str, Any] | None) -> Path:
    config = config if config is not None else resolve_config_auto()
    rel = config.get("paths", {}).get("model_catalog", "catalog/model_catalog.yaml")
    return Path(rel)


def load_catalog(config: dict[str, Any] | None = None) -> dict[str, ModelTier]:
    path = _catalog_path(config)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    tiers = raw.get("tiers", {})
    return {name: ModelTier(name=name, **fields) for name, fields in tiers.items()}
