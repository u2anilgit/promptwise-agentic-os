from core.routing.catalog import load_catalog, tier_order
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
    assert set(tier_order(catalog)) == set(catalog.keys())


def test_tier_order_is_local_before_cloud_and_cheapest_first():
    catalog = load_catalog()
    order = tier_order(catalog)
    assert order == ["local-small", "local-large", "cloud-cheap", "cloud-premium"]


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


def test_load_catalog_falls_back_to_packaged_copy_when_resolved_path_missing():
    config = {"paths": {"model_catalog": "does/not/exist.yaml"}}
    catalog = load_catalog(config)
    assert set(catalog.keys()) == {"local-small", "local-large", "cloud-cheap", "cloud-premium"}


def test_load_catalog_resolves_relative_default_path_against_cwd(tmp_path, monkeypatch):
    # Simulate promptwise doctor/gateway invoked from a different cwd than
    # the repo root — the relative default should still resolve, or fall
    # back to the packaged copy, never raise a bare FileNotFoundError from a
    # CWD-relative lookup.
    monkeypatch.chdir(tmp_path)
    catalog = load_catalog({})
    assert set(catalog.keys()) == {"local-small", "local-large", "cloud-cheap", "cloud-premium"}
