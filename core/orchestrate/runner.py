# core/orchestrate/runner.py
"""orchestrate_tasks — the public verb. Topological execution of a Dag's
nodes: each node's `run` callable is invoked with its dependencies'
outputs plus a `routing_decision` hint from route_request. One node
failing marks it (and everything downstream of it) as not done, but
never aborts the whole call — independent branches still run (design
spec Ruling 4). The one exception: a structurally invalid DAG (cycle,
dangling reference) raises ValueError before any node runs.
"""
from __future__ import annotations

from typing import Any

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagResult, NodeResult
from core.routing.router import RouteRequest, route_request


def orchestrate_tasks(dag: Dag, config: dict[str, Any] | None = None) -> DagResult:
    order = topological_order(dag)  # raises ValueError on cycle/dangling ref before anything runs
    config = config if config is not None else resolve_config_auto()
    nodes_by_id = {node.id: node for node in dag.nodes}

    results: dict[str, NodeResult] = {}
    for node_id in order:
        node = nodes_by_id[node_id]
        dep_failed = any(results[dep].status != "done" for dep in node.depends_on)

        if dep_failed:
            results[node_id] = NodeResult(status="skipped", error="a dependency did not complete")
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="error", detail={"reason": "dependency failed or skipped"},
            )
            continue

        decision = route_request(
            RouteRequest(task_type=node.task_type, privacy_sensitive=node.privacy_sensitive),
            config=config,
        )
        inputs: dict[str, Any] = {dep: results[dep].output for dep in node.depends_on}
        inputs["routing_decision"] = decision

        try:
            output = node.run(inputs)
            results[node_id] = NodeResult(status="done", output=output)
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="allow", detail={"tier": decision.tier},
            )
        except Exception as exc:  # noqa: BLE001 — one node's failure must not abort the DAG
            results[node_id] = NodeResult(status="error", error=str(exc))
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="error", detail={"error": str(exc)},
            )

    return DagResult(dag_name=dag.name, nodes=results)
