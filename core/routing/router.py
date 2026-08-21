# core/routing/router.py
"""route_request — docs/research/aug2026-findings.md Part 5 row 5.

Pure selection logic: given a request, the machine's hardware, config, and
the model catalog, pick the cheapest/smallest tier that satisfies both the
privacy constraint and the RAM budget, falling back gracefully — never
raising — when the preferred tier doesn't fit or doesn't exist.
"""
from __future__ import annotations

from pydantic import BaseModel

from core.config.resolve import resolve_config_auto
from core.diagnostics.hardware import HardwareProfile, detect_hardware
from core.routing.catalog import load_catalog, tier_order
from core.routing.models import ModelTier


class RouteRequest(BaseModel):
    task_type: str = "general"
    privacy_sensitive: bool = False
    preferred_tier: str | None = None


class RoutingDecision(BaseModel):
    tier: str
    provider: str
    model_id: str
    reason: str
    fallback_applied: bool
    privacy_forced: bool = False


def _eligible_tiers(catalog: dict[str, ModelTier], local_only: bool) -> list[str]:
    ordered = [name for name in tier_order(catalog) if name in catalog]
    if local_only:
        ordered = [name for name in ordered if not catalog[name].requires_cloud]
    return ordered


def route_request(
    request: RouteRequest,
    hardware: HardwareProfile | None = None,
    config: dict | None = None,
    catalog: dict[str, ModelTier] | None = None,
) -> RoutingDecision:
    config = config if config is not None else resolve_config_auto()
    hardware = hardware if hardware is not None else detect_hardware()
    catalog = catalog if catalog is not None else load_catalog(config)

    local_only = bool(config.get("engine", {}).get("local_only", True)) or request.privacy_sensitive
    eligible = _eligible_tiers(catalog, local_only)
    if not eligible:
        raise ValueError("no eligible tiers in catalog for this request — check catalog and local_only/privacy settings")

    default_tier = config.get("routing", {}).get("default_tier")

    privacy_forced = False
    if (
        local_only
        and request.preferred_tier
        and request.preferred_tier in catalog
        and catalog[request.preferred_tier].requires_cloud
        and request.preferred_tier not in eligible
    ):
        privacy_forced = True

    if request.preferred_tier and request.preferred_tier in eligible:
        target = request.preferred_tier
        reason = f"selected {target} (explicitly preferred)"
    elif default_tier and default_tier in eligible:
        target = default_tier
        reason = f"selected {target} (configured default tier)"
    else:
        target = eligible[0]
        reason = f"selected {target} (smallest eligible tier)"

    if privacy_forced:
        reason += " — privacy override: local_only excluded the requested cloud tier"

    fallback_applied = False
    if not hardware.ram_detected:
        # Unknown RAM (sentinel 0.0/0.0) — never attempt the watchdog
        # comparison, since 0.0 available RAM would otherwise look like
        # "nothing fits" and silently escalate to whatever cloud tier
        # happens to be smallest/cheapest. Keep whatever was already
        # selected via the normal preferred/default/eligible[0] logic.
        reason += " (RAM could not be detected on this platform — watchdog skipped)"
    elif catalog[target].min_ram_gb > hardware.available_ram_gb:
        fitting = [name for name in eligible if catalog[name].min_ram_gb <= hardware.available_ram_gb]
        if fitting:
            target = fitting[0]
            fallback_applied = True
            reason = (
                f"RAM watchdog: preferred/default tier needed more RAM than the "
                f"{hardware.available_ram_gb}GB available — fell back to {target}"
            )
        else:
            target = eligible[0]
            fallback_applied = True
            reason = (
                f"RAM watchdog: no eligible tier fits {hardware.available_ram_gb}GB available — "
                f"using smallest eligible tier {target} anyway, expect degraded performance"
            )

    tier_obj = catalog[target]
    return RoutingDecision(
        tier=target,
        provider=tier_obj.provider,
        model_id=tier_obj.model_id,
        reason=reason,
        fallback_applied=fallback_applied,
        privacy_forced=privacy_forced,
    )
