from core.routing.catalog import TIER_ORDER, load_catalog
from core.routing.models import ModelTier


def test_load_catalog_returns_a_model_tier_per_entry():
    catalog = load_catalog()
    assert set(catalog.keys()) == {"local-small", "local-large", "cloud-cheap", "cloud-premium"}
    for tier in catalog.values():
        assert isinstance(tier, ModelTier)


def test_local_tiers_are_free_and_not_cloud():
    catalog = load_catalog()
    for name in ("local-small", "local-large"):
        assert catalog[name].requires_cloud is False
        assert catalog[name].cost_per_1k_input_usd == 0.0
        assert catalog[name].cost_per_1k_output_usd == 0.0


def test_cloud_tiers_require_cloud_and_cost_money():
    catalog = load_catalog()
    for name in ("cloud-cheap", "cloud-premium"):
        assert catalog[name].requires_cloud is True
        assert catalog[name].cost_per_1k_input_usd > 0.0


def test_tier_order_matches_catalog_keys():
    catalog = load_catalog()
    assert set(TIER_ORDER) == set(catalog.keys())


def test_load_catalog_respects_configured_path(tmp_path):
    custom = tmp_path / "custom_catalog.yaml"
    custom.write_text(
        "tiers:\n"
        "  only-tier:\n"
        "    provider: ollama\n"
        "    model_id: test-model\n"
        "    min_ram_gb: 1.0\n"
        "    requires_cloud: false\n"
        "    cost_per_1k_input_usd: 0.0\n"
        "    cost_per_1k_output_usd: 0.0\n"
    )
    config = {"paths": {"model_catalog": str(custom)}}
    catalog = load_catalog(config)
    assert set(catalog.keys()) == {"only-tier"}
