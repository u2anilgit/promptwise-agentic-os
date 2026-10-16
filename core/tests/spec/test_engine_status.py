import pytest

from core.spec.engine import complete_task, plan_feature, spec_status, specify_feature, tasks_feature

from .conftest import REQS, STANDARD_CHECKS, checks, interactive_tasks


def test_status_of_a_fresh_spec_shows_stage_requirements_and_no_tasks(project):
    tmp, config = project
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    status = spec_status(spec.spec_id, config=config, root=tmp)
    assert status.stage == "specified" and status.request == "add login"
    assert [r.id for r in status.requirements] == ["R1", "R2"] and status.tasks == []


def test_status_tracks_tasks_as_they_complete(project):
    tmp, config = project
    config["verify"]["test_command"] = 'python -c "pass"'
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    tasks_feature(spec.spec_id, interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    assert {t.task_id: t.status for t in spec_status(spec.spec_id, config=config, root=tmp).tasks} == {"t1": "pending", "t2": "pending"}
    assert complete_task(spec.spec_id, "t1", "e", config=config, root=tmp).accepted
    after = spec_status(spec.spec_id, config=config, root=tmp)
    assert after.stage == "implementing" and {t.task_id: t.status for t in after.tasks}["t1"] == "done"


def test_status_of_an_unknown_spec_raises_value_error(project):
    tmp, config = project
    with pytest.raises(ValueError, match="unknown spec"):
        spec_status("ghost", config=config, root=tmp)
