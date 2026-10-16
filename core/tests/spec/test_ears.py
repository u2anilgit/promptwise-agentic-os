import pytest

from core.spec.ears import validate_ears
from core.spec.models import Requirement


def _r(text, i=1):
    return Requirement(id=f"R{i}", text=text)


@pytest.mark.parametrize(
    "text",
    [
        "The system shall log every request.",
        "When a user logs in, the system shall record the timestamp.",
        "While the gate is locked, the system shall reject all writes.",
        "If the disk is full, then the system shall pause ingestion.",
        "Where telemetry is enabled, the system shall emit metrics.",
    ],
)
def test_each_ears_shape_passes(text):
    assert validate_ears([_r(text)]) == []


def test_non_ears_sentence_is_flagged_with_its_requirement_id():
    violations = validate_ears([_r("make it fast", 7)])
    assert len(violations) == 1
    assert violations[0].requirement_id == "R7"
    assert violations[0].reason == "does not match any EARS sentence shape"


def test_mixed_list_flags_only_the_bad_one():
    violations = validate_ears([_r("The system shall log every request.", 1), _r("make it fast", 2)])
    assert [v.requirement_id for v in violations] == ["R2"]


def test_empty_list_has_no_violations():
    assert validate_ears([]) == []
