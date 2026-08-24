import pytest

from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagNode


def _node(node_id, depends_on=None):
    return DagNode(id=node_id, run=lambda inputs: None, depends_on=depends_on or [])


def test_topological_order_orders_a_simple_chain():
    dag = Dag(name="chain", nodes=[_node("c", ["b"]), _node("a"), _node("b", ["a"])])
    order = topological_order(dag)
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_order_includes_every_node_exactly_once():
    dag = Dag(name="diamond", nodes=[_node("a"), _node("b", ["a"]), _node("c", ["a"]), _node("d", ["b", "c"])])
    order = topological_order(dag)
    assert sorted(order) == ["a", "b", "c", "d"]
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_topological_order_handles_independent_nodes():
    dag = Dag(name="independent", nodes=[_node("a"), _node("b")])
    order = topological_order(dag)
    assert set(order) == {"a", "b"}


def test_topological_order_raises_on_a_dangling_dependency():
    dag = Dag(name="dangling", nodes=[_node("a", ["does-not-exist"])])
    with pytest.raises(ValueError, match="unknown node"):
        topological_order(dag)


def test_topological_order_raises_on_a_cycle():
    dag = Dag(name="cycle", nodes=[_node("a", ["b"]), _node("b", ["a"])])
    with pytest.raises(ValueError, match="cycle"):
        topological_order(dag)


def test_topological_order_on_an_empty_dag_returns_empty_list():
    dag = Dag(name="empty", nodes=[])
    assert topological_order(dag) == []
