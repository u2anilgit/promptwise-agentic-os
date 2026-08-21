# core/tests/routing/test_router.py
import pytest

from core.diagnostics.hardware import HardwareProfile
from core.routing.catalog import load_catalog
from core.routing.models import ModelTier
from core.routing.router import RouteRequest, route_request


@pytest.fixture
def catalog():
    return load_catalog()


def test_default_request_picks_configured_default_tier(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(RouteRequest(), hardware=hw, config=config, catalog=catalog)
    assert decision.tier == "local-small"
    assert decision.provider == "ollama"
    assert decision.fallback_applied is False


def test_preferred_tier_is_honored_when_it_fits(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-large"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-large"
    assert decision.fallback_applied is False


def test_ram_watchdog_falls_back_a_tier_when_preferred_does_not_fit(catalog):
    hw = HardwareProfile(total_ram_gb=8.0, available_ram_gb=6.0, cpu_count=4, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-large"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-small"  # local-large needs 12GB, only 6GB available
    assert decision.fallback_applied is True
    assert "watchdog" in decision.reason.lower()


def test_ram_watchdog_never_crashes_when_nothing_fits(catalog):
    hw = HardwareProfile(total_ram_gb=2.0, available_ram_gb=1.0, cpu_count=2, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(RouteRequest(), hardware=hw, config=config, catalog=catalog)
    assert decision.tier == "local-small"  # smallest eligible tier, used anyway
    assert decision.fallback_applied is True


def test_privacy_sensitive_request_never_selects_a_cloud_tier(catalog):
    hw = HardwareProfile(total_ram_gb=64.0, available_ram_gb=60.0, cpu_count=16, has_gpu=True)
    # local_only False at the config level — only the per-request flag should force local
    config = {"engine": {"local_only": False}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(privacy_sensitive=True, preferred_tier="cloud-premium"),
        hardware=hw,
        config=config,
        catalog=catalog,
    )
    assert decision.tier in ("local-small", "local-large")
    assert decision.provider == "ollama"


def test_local_only_config_forces_local_even_without_privacy_flag(catalog):
    hw = HardwareProfile(total_ram_gb=64.0, available_ram_gb=60.0, cpu_count=16, has_gpu=True)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="cloud-premium"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.provider == "ollama"


def test_non_local_only_config_can_select_a_cloud_tier(catalog):
    hw = HardwareProfile(total_ram_gb=4.0, available_ram_gb=2.0, cpu_count=2, has_gpu=False)
    config = {"engine": {"local_only": False}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="cloud-cheap"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "cloud-cheap"
    assert decision.provider == "anthropic"


def test_unknown_preferred_tier_falls_back_to_default_instead_of_crashing(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="does-not-exist"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-small"


def test_ram_undetected_skips_watchdog_and_never_escalates_to_cloud(catalog):
    # ram_detected=False means available_ram_gb is a meaningless 0.0 sentinel.
    # Without the skip, the watchdog would see "nothing fits" and fall back
    # to eligible[0] — which, if local_only were ever false, could be a
    # cloud tier that was never actually requested or defaulted to.
    hw = HardwareProfile(
        total_ram_gb=0.0, available_ram_gb=0.0, cpu_count=4, has_gpu=False, ram_detected=False
    )
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-large"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-large"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-large"
    assert decision.fallback_applied is False
    assert decision.provider == "ollama"
    assert "could not be detected" in decision.reason.lower()


def test_operator_added_tier_is_selectable_without_touching_core(catalog):
    extra_catalog = dict(catalog)
    extra_catalog["local-medium"] = ModelTier(
        name="local-medium",
        provider="ollama",
        model_id="test-medium",
        min_ram_gb=8.0,
        requires_cloud=False,
        cost_per_1k_input_usd=0.0,
        cost_per_1k_output_usd=0.0,
    )
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-medium"), hardware=hw, config=config, catalog=extra_catalog
    )
    assert decision.tier == "local-medium"
    assert decision.fallback_applied is False


def test_privacy_forced_true_when_cloud_tier_excluded_by_local_only(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": False}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(privacy_sensitive=True, preferred_tier="cloud-premium"),
        hardware=hw,
        config=config,
        catalog=catalog,
    )
    assert decision.privacy_forced is True
    assert decision.tier in ("local-small", "local-large")


def test_privacy_forced_false_for_normal_local_only_default_request(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(RouteRequest(), hardware=hw, config=config, catalog=catalog)
    assert decision.privacy_forced is False
