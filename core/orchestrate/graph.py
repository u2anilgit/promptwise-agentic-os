# core/orchestrate/graph.py
"""Kahn's algorithm — pure function, no I/O. Raises ValueError immediately
on a structurally invalid DAG (a cycle, or a node depending on an id
that doesn't exist) rather than silently skipping or partially ordering
it — this is a caller programming error, not a runtime failure to
degrade through (design spec Ruling 4).
"""
from __future__ import annotations

from core.orchestrate.models import Dag


def topological_order(dag: Dag) -> list[str]:
    node_ids = {node.id for node in dag.nodes}
    for node in dag.nodes:
        for dep in node.depends_on:
            if dep not in node_ids:
                raise ValueError(f"node {node.id!r} depends on unknown node {dep!r}")

    in_degree = {node.id: len(node.depends_on) for node in dag.nodes}
    dependents: dict[str, list[str]] = {node.id: [] for node in dag.nodes}
    for node in dag.nodes:
        for dep in node.depends_on:
            dependents[dep].append(node.id)

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(dag.nodes):
        raise ValueError("dag contains a cycle")

    return order
