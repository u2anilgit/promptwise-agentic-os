from core.spec.engine import complete_task, list_specs, plan_feature, specify_feature, tasks_feature
from core.spec.models import TaskNode

from .conftest import REQS, checks


def test_no_specs_is_an_empty_list(project):
    tmp, config = project
    assert list_specs(config=config, root=tmp) == []


def test_lists_specs_newest_first_with_stage_and_task_counts(project):
    tmp, config = project
    config["verify"]["test_command"] = 'python -c "pass"'
    older = specify_feature("login", REQS, config=config, root=tmp)
    newer = specify_feature("billing", [REQS[0]], config=config, root=tmp)
    plan_feature(older.spec_id, "approach", config=config, root=tmp)
    tasks_feature(
        older.spec_id,
        [TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2", requirement_ids=["R2"])],
        checks(("R1", "check_login.py"), ("R2", "check_logout.py")),
        config=config, root=tmp,
    )
    complete_task(older.spec_id, "t1", "done", config=config, root=tmp)

    summaries = list_specs(config=config, root=tmp)
    assert [s.spec_id for s in summaries] == [newer.spec_id, older.spec_id]
    by_id = {s.spec_id: s for s in summaries}
    assert (by_id[newer.spec_id].stage, by_id[newer.spec_id].tasks_total, by_id[newer.spec_id].tasks_done) == ("specified", 0, 0)
    assert (by_id[older.spec_id].stage, by_id[older.spec_id].tasks_total, by_id[older.spec_id].tasks_done) == ("implementing", 2, 1)
    assert by_id[older.spec_id].request == "login"
