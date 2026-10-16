import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from core.db.base import make_engine, session_scope
from core.db.migrate import migrate_to_head
from core.spec import store
from core.spec.models import FrozenCheck, PlanArtifact, Requirement, SpecArtifact, TaskNode


@pytest.fixture
def config(tmp_path):
    cfg = {"database": {"url": f"sqlite:///{(tmp_path / 's.db').as_posix()}"}}
    migrate_to_head(cfg)
    return cfg


def _spec(spec_id="s1"):
    return SpecArtifact(
        spec_id=spec_id, request="add login", complexity="standard", created_at=10.0,
        requirements=[Requirement(id="R1", text="The system shall log in."), Requirement(id="R2", text="The system shall log out.")],
    )


def test_migration_creates_the_spec_tables(config):
    names = set(inspect(make_engine(config)).get_table_names())
    assert {"spec", "spec_requirement", "plan", "spec_stage", "task", "acceptance_check"} <= names


def test_spec_round_trips_with_ordered_requirements(config):
    with session_scope(config) as s:
        store.save_spec(s, _spec())
    with session_scope(config) as s:
        got = store.get_spec(s, "s1")
    assert got == _spec()


def test_get_spec_and_stage_for_unknown_id_are_none(config):
    with session_scope(config) as s:
        assert store.get_spec(s, "nope") is None
        assert store.get_stage(s, "nope") is None
        assert store.get_plan(s, "nope") is None


def test_stage_is_set_and_updated(config):
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        store.set_stage(s, "s1", "specified")
        store.set_stage(s, "s1", "planned")
    with session_scope(config) as s:
        assert store.get_stage(s, "s1") == "planned"


def test_plan_round_trips_including_requirements_hash(config):
    plan = PlanArtifact(spec_id="s1", approach="do it", created_at=11.0, requirements_sha256="abc")
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        store.save_plan(s, plan)
    with session_scope(config) as s:
        assert store.get_plan(s, "s1") == plan


def test_plan_for_unknown_spec_violates_the_foreign_key(config):
    with pytest.raises(IntegrityError):
        with session_scope(config) as s:
            store.save_plan(s, PlanArtifact(spec_id="ghost", approach="a", created_at=1.0))


def test_tasks_round_trip_and_status_updates(config):
    tasks = [TaskNode(id="t1", requirement_ids=["R1"], run=lambda i: 1), TaskNode(id="t2", depends_on=["t1"], requirement_ids=["R2"], expected_symbols=["login"])]
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        store.save_tasks(s, "s1", tasks)
        store.set_task_status(s, "s1", "t1", "done")
        store.set_task_status(s, "s1", "t2", "error", error="boom")
    with session_scope(config) as s:
        records = {r.task_id: r for r in store.get_tasks(s, "s1")}
    assert records["t1"].status == "done" and records["t1"].interactive is False
    assert records["t2"].status == "error" and records["t2"].error == "boom"
    assert records["t2"].interactive is True and records["t2"].depends_on == ["t1"]
    assert records["t2"].expected_symbols == ["login"]


def test_set_task_status_for_unknown_task_raises_value_error(config):
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        with pytest.raises(ValueError, match="unknown task"):
            store.set_task_status(s, "s1", "ghost", "done")


def test_frozen_checks_round_trip_and_replace_returns_the_old_one(config):
    old = FrozenCheck(requirement_id="R1", command="python check.py", files=["check.py"], file_hashes={"check.py": "h1"})
    new = FrozenCheck(requirement_id="R1", command="python check2.py", files=["check2.py"], file_hashes={"check2.py": "h2"})
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        store.save_frozen_checks(s, "s1", [old])
    with session_scope(config) as s:
        assert store.get_frozen_checks(s, "s1") == [old]
        assert store.replace_frozen_check(s, "s1", "R1", new) == old
    with session_scope(config) as s:
        assert store.get_frozen_checks(s, "s1") == [new]


def test_replace_frozen_check_for_unknown_requirement_raises_value_error(config):
    with session_scope(config) as s:
        store.save_spec(s, _spec())
        with pytest.raises(ValueError, match="no frozen check"):
            store.replace_frozen_check(s, "s1", "R9", FrozenCheck(requirement_id="R9", command="c"))


def test_migrations_match_the_declared_models(config):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    import core.spec.tables  # noqa: F401
    from core.db.base import Base

    with make_engine(config).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
