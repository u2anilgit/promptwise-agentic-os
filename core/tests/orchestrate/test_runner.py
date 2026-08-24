import pytest

from core.orchestrate.models import Dag, DagNode
from core.orchestrate.runner import orchestrate_tasks


def _config(tmp_path):
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
    }


def test_orchestrate_tasks_runs_a_chain_and_threads_outputs(tmp_path):
    dag = Dag(
        name="chain",
        nodes=[
            DagNode(id="a", run=lambda inputs: 10),
            DagNode(id="b", run=lambda inputs: inputs["a"] + 5, depends_on=["a"]),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "done"
    assert result.nodes["a"].output == 10
    assert result.nodes["b"].status == "done"
    assert result.nodes["b"].output == 15


def test_orchestrate_tasks_skips_dependents_of_a_failed_node(tmp_path):
    def failing(inputs):
        raise RuntimeError("boom")

    dag = Dag(
        name="fail-chain",
        nodes=[
            DagNode(id="a", run=failing),
            DagNode(id="b", run=lambda inputs: "should not run", depends_on=["a"]),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "error"
    assert "boom" in result.nodes["a"].error
    assert result.nodes["b"].status == "skipped"


def test_orchestrate_tasks_runs_independent_branches_even_if_one_fails(tmp_path):
    def failing(inputs):
        raise RuntimeError("boom")

    dag = Dag(
        name="independent",
        nodes=[
            DagNode(id="a", run=failing),
            DagNode(id="b", run=lambda inputs: "ok"),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "error"
    assert result.nodes["b"].status == "done"
    assert result.nodes["b"].output == "ok"


def test_orchestrate_tasks_raises_immediately_on_a_cyclic_dag_and_runs_nothing(tmp_path):
    ran = []
    dag = Dag(
        name="cycle",
        nodes=[
            DagNode(id="a", run=lambda inputs: ran.append("a"), depends_on=["b"]),
            DagNode(id="b", run=lambda inputs: ran.append("b"), depends_on=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        orchestrate_tasks(dag, config=_config(tmp_path))
    assert ran == []


def test_orchestrate_tasks_attaches_a_routing_decision_to_node_inputs(tmp_path):
    captured = {}

    def capture(inputs):
        captured["decision"] = inputs["routing_decision"]
        return "ok"

    dag = Dag(name="routed", nodes=[DagNode(id="a", run=capture, task_type="code_review")])
    orchestrate_tasks(dag, config=_config(tmp_path))
    assert captured["decision"].tier == "local-small"
    assert captured["decision"].provider == "ollama"


def test_orchestrate_tasks_on_an_empty_dag_returns_empty_results(tmp_path):
    dag = Dag(name="empty", nodes=[])
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.dag_name == "empty"
    assert result.nodes == {}
