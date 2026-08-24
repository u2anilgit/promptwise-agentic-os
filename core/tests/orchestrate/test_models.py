from core.orchestrate.models import Dag, DagNode, DagResult, NodeResult


def test_dag_node_defaults():
    node = DagNode(id="a", run=lambda inputs: "output")
    assert node.id == "a"
    assert node.depends_on == []
    assert node.task_type == "general"
    assert node.privacy_sensitive is False
    assert node.run({}) == "output"


def test_dag_node_with_dependencies():
    node = DagNode(id="b", run=lambda inputs: inputs, depends_on=["a"], task_type="code_review")
    assert node.depends_on == ["a"]
    assert node.task_type == "code_review"


def test_dag_holds_nodes():
    nodes = [DagNode(id="a", run=lambda inputs: 1), DagNode(id="b", run=lambda inputs: 2, depends_on=["a"])]
    dag = Dag(name="example", nodes=nodes)
    assert dag.name == "example"
    assert len(dag.nodes) == 2


def test_node_result_defaults():
    result = NodeResult(status="done")
    assert result.status == "done"
    assert result.output is None
    assert result.error is None


def test_node_result_with_error():
    result = NodeResult(status="error", error="boom")
    assert result.status == "error"
    assert result.error == "boom"


def test_dag_result_holds_node_results():
    result = DagResult(dag_name="example", nodes={"a": NodeResult(status="done", output=1)})
    assert result.dag_name == "example"
    assert result.nodes["a"].output == 1
