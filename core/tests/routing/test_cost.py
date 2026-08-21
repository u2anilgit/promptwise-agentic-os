from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report, record_cost


def test_record_cost_is_zero_for_local_tiers():
    catalog = load_catalog()
    record = CostRecord(tier="local-small", tokens_in=10_000, tokens_out=5_000)
    assert record_cost(record, catalog["local-small"]) == 0.0


def test_record_cost_computes_from_per_1k_rates():
    catalog = load_catalog()
    tier = catalog["cloud-cheap"]
    record = CostRecord(tier="cloud-cheap", tokens_in=2_000, tokens_out=1_000)
    expected = (2_000 / 1000) * tier.cost_per_1k_input_usd + (1_000 / 1000) * tier.cost_per_1k_output_usd
    assert record_cost(record, tier) == expected


def test_cost_report_computes_total_and_per_task_average():
    catalog = load_catalog()
    records = [
        CostRecord(tier="local-small", tokens_in=1_000, tokens_out=500),
        CostRecord(tier="cloud-cheap", tokens_in=1_000, tokens_out=500),
    ]
    report = cost_report(records, catalog)
    expected_total = record_cost(records[0], catalog["local-small"]) + record_cost(records[1], catalog["cloud-cheap"])
    assert report["completed_tasks"] == 2
    assert report["total_cost_usd"] == round(expected_total, 6)
    assert report["cost_per_completed_task_usd"] == round(expected_total / 2, 6)


def test_cost_report_breaks_down_by_tier():
    catalog = load_catalog()
    records = [
        CostRecord(tier="local-small", tokens_in=1_000, tokens_out=500),
        CostRecord(tier="local-small", tokens_in=2_000, tokens_out=1_000),
        CostRecord(tier="cloud-cheap", tokens_in=1_000, tokens_out=500),
    ]
    report = cost_report(records, catalog)
    assert report["by_tier"]["local-small"]["tasks"] == 2
    assert report["by_tier"]["cloud-cheap"]["tasks"] == 1


def test_cost_report_handles_zero_records_without_crashing():
    catalog = load_catalog()
    report = cost_report([], catalog)
    assert report["completed_tasks"] == 0
    assert report["total_cost_usd"] == 0.0
    assert report["cost_per_completed_task_usd"] == 0.0
    assert report["by_tier"] == {}
