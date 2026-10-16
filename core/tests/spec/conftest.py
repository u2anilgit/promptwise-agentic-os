import json

import pytest

from core.spec.models import AcceptanceCheck, TaskNode

REQS = ["The system shall log in users.", "The system shall log out users."]


@pytest.fixture
def project(tmp_path):
    """A tiny real project: two check scripts that exit 0, a DB, an audit log."""
    (tmp_path / "check_login.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / "check_logout.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    config = {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "database": {"url": f"sqlite:///{(tmp_path / 'spec.db').as_posix()}"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "verify": {"test_command": "", "lint_command": "", "failure_ledger_path": str(tmp_path / "ledger.json")},
        "spec": {"allow_ungrounded": False, "trivial_max_requirements": 1, "check_timeout_seconds": 20},
    }
    return tmp_path, config


def checks(*pairs):
    return [AcceptanceCheck(requirement_id=r, command=f"python {f}", files=[f]) for r, f in pairs]


STANDARD_CHECKS = (("R1", "check_login.py"), ("R2", "check_logout.py"))


def interactive_tasks():
    return [TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2", requirement_ids=["R2"], depends_on=["t1"])]


def audit_records(tmp_path):
    p = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
