import pytest
from pydantic import ValidationError

from core.spec.models import (
    AcceptanceCheck,
    ConvergeReport,
    FrozenCheck,
    PlanArtifact,
    Requirement,
    SpecArtifact,
    TaskNode,
)


def test_requirement_requires_id_and_text():
    with pytest.raises(ValidationError):
        Requirement(id="R1")  # type: ignore[call-arg]


def test_acceptance_check_defaults_files_to_empty():
    assert AcceptanceCheck(requirement_id="R1", command="python -c pass").files == []


def test_frozen_check_extends_acceptance_check_with_hashes():
    fc = FrozenCheck(requirement_id="R1", command="c", files=["a.py"], file_hashes={"a.py": "abc"})
    assert fc.file_hashes == {"a.py": "abc"}


def test_task_node_defaults_are_interactive_and_independent():
    node = TaskNode(id="t1")
    assert node.run is None
    assert node.depends_on == [] and node.requirement_ids == [] and node.expected_symbols == []
    assert node.task_type == "general"


def test_task_node_accepts_a_callable():
    assert TaskNode(id="t1", run=lambda inputs: 1).run is not None


def test_spec_complexity_is_restricted():
    with pytest.raises(ValidationError):
        SpecArtifact(spec_id="s", request="r", complexity="huge", requirements=[], created_at=0.0)  # type: ignore[arg-type]


def test_plan_and_converge_report_shapes():
    assert PlanArtifact(spec_id="s", approach="a", created_at=1.0).approach == "a"
    report = ConvergeReport(spec_id="s", planned_tasks=2, done_tasks=1, pending_tasks=1, stale=False, reasons=[])
    assert report.reasons == []
