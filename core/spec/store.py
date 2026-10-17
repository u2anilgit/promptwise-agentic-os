# core/spec/store.py — repository functions over a SQLAlchemy Session.
# Callers own the transaction (core.db.base.session_scope commits / rolls back).
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.spec.models import (
    FrozenCheck,
    PlanArtifact,
    Requirement,
    SpecArtifact,
    SpecSummary,
    TaskNode,
    TaskRecord,
)
from core.spec.tables import CheckRow, PlanRow, RequirementRow, SpecRow, StageRow, TaskTable


def save_spec(session: Session, spec: SpecArtifact) -> None:
    session.add(SpecRow(spec_id=spec.spec_id, request=spec.request, complexity=spec.complexity, created_at=spec.created_at))
    session.flush()  # parent row before children (FK enforcement)
    for position, req in enumerate(spec.requirements):
        session.add(RequirementRow(spec_id=spec.spec_id, req_id=req.id, text=req.text, position=position))
    session.flush()


def get_spec(session: Session, spec_id: str) -> SpecArtifact | None:
    row = session.get(SpecRow, spec_id)
    if row is None:
        return None
    reqs = session.scalars(
        select(RequirementRow).where(RequirementRow.spec_id == spec_id).order_by(RequirementRow.position)
    ).all()
    return SpecArtifact(
        spec_id=row.spec_id,
        request=row.request,
        complexity=row.complexity,  # type: ignore[arg-type]
        requirements=[Requirement(id=r.req_id, text=r.text) for r in reqs],
        created_at=row.created_at,
    )


def get_stage(session: Session, spec_id: str) -> str | None:
    row = session.get(StageRow, spec_id)
    return row.stage if row else None


def set_stage(session: Session, spec_id: str, stage: str) -> None:
    row = session.get(StageRow, spec_id)
    if row is None:
        session.add(StageRow(spec_id=spec_id, stage=stage))
    else:
        row.stage = stage
    session.flush()


def save_plan(session: Session, plan: PlanArtifact) -> None:
    session.add(
        PlanRow(
            spec_id=plan.spec_id,
            approach=plan.approach,
            created_at=plan.created_at,
            requirements_sha256=plan.requirements_sha256,
        )
    )
    session.flush()


def get_plan(session: Session, spec_id: str) -> PlanArtifact | None:
    row = session.get(PlanRow, spec_id)
    if row is None:
        return None
    return PlanArtifact(
        spec_id=row.spec_id,
        approach=row.approach,
        created_at=row.created_at,
        requirements_sha256=row.requirements_sha256,
    )


def save_tasks(session: Session, spec_id: str, tasks: list[TaskNode]) -> None:
    for t in tasks:
        session.add(
            TaskTable(
                spec_id=spec_id,
                task_id=t.id,
                status="pending",
                requirement_ids=list(t.requirement_ids),
                depends_on=list(t.depends_on),
                expected_symbols=list(t.expected_symbols),
                interactive=t.run is None,
            )
        )
    session.flush()


def _task_record(row: TaskTable) -> TaskRecord:
    return TaskRecord(
        task_id=row.task_id,
        status=row.status,  # type: ignore[arg-type]
        requirement_ids=list(row.requirement_ids),
        depends_on=list(row.depends_on),
        expected_symbols=list(row.expected_symbols),
        interactive=row.interactive,
        error=row.error,
    )


def get_tasks(session: Session, spec_id: str) -> list[TaskRecord]:
    rows = session.scalars(select(TaskTable).where(TaskTable.spec_id == spec_id).order_by(TaskTable.pk)).all()
    return [_task_record(r) for r in rows]


def set_task_status(session: Session, spec_id: str, task_id: str, status: str, error: str | None = None) -> None:
    row = session.scalars(select(TaskTable).where(TaskTable.spec_id == spec_id, TaskTable.task_id == task_id)).first()
    if row is None:
        raise ValueError(f"unknown task '{task_id}' for spec '{spec_id}'")
    row.status = status
    row.error = error
    session.flush()


def _check_from_row(row: CheckRow) -> FrozenCheck:
    return FrozenCheck(
        requirement_id=row.requirement_id,
        command=row.command,
        files=list(row.files),
        file_hashes=dict(row.file_hashes),
        expect_baseline=row.expect_baseline,  # type: ignore[arg-type]
        baseline=row.baseline,  # type: ignore[arg-type]
    )


def save_frozen_checks(session: Session, spec_id: str, checks: list[FrozenCheck]) -> None:
    now = time.time()
    for c in checks:
        session.add(
            CheckRow(
                spec_id=spec_id,
                requirement_id=c.requirement_id,
                command=c.command,
                files=list(c.files),
                file_hashes=dict(c.file_hashes),
                frozen_at=now,
                expect_baseline=c.expect_baseline,
                baseline=c.baseline,
            )
        )
    session.flush()


def get_frozen_checks(session: Session, spec_id: str) -> list[FrozenCheck]:
    rows = session.scalars(select(CheckRow).where(CheckRow.spec_id == spec_id).order_by(CheckRow.pk)).all()
    return [_check_from_row(r) for r in rows]


def replace_frozen_check(session: Session, spec_id: str, requirement_id: str, new: FrozenCheck) -> FrozenCheck:
    row = session.scalars(
        select(CheckRow).where(CheckRow.spec_id == spec_id, CheckRow.requirement_id == requirement_id)
    ).first()
    if row is None:
        raise ValueError(f"no frozen check for requirement '{requirement_id}' of spec '{spec_id}'")
    old = _check_from_row(row)
    row.command, row.files, row.file_hashes, row.frozen_at = new.command, list(new.files), dict(new.file_hashes), time.time()
    row.expect_baseline, row.baseline = new.expect_baseline, new.baseline
    session.flush()
    return old


def list_specs(session: Session) -> list[SpecSummary]:
    rows = session.scalars(select(SpecRow).order_by(SpecRow.created_at.desc(), SpecRow.spec_id.desc())).all()
    out = []
    for row in rows:
        tasks = get_tasks(session, row.spec_id)
        out.append(SpecSummary(
            spec_id=row.spec_id, request=row.request, complexity=row.complexity,
            stage=get_stage(session, row.spec_id) or "specified", created_at=row.created_at,
            tasks_total=len(tasks), tasks_done=sum(1 for t in tasks if t.status == "done"),
        ))
    return out
