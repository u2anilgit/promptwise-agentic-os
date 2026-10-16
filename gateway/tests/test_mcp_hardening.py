"""Findings from the security review of feat/mcp-exposure (each reproduced RED first)."""
import json
from pathlib import Path

import pytest

from core.audit.log import verify_chain
from core.config.resolve import resolve_config_auto
from gateway import mcp_guard
from gateway.mcp_guard import effective_config, operator_config, run_governed
from gateway.mcp_server import mcp_app

from .test_mcp_guard import DESC, SCHEMA, _audit, _lookup, _operator


def _project(tmp_path, yaml_text):
    project = tmp_path / "work"
    (project / ".promptwise").mkdir(parents=True, exist_ok=True)
    (project / ".promptwise" / "config.yaml").write_text(yaml_text, encoding="utf-8")
    return project


# ---- C1 / I1: governance state and endpoints come from the operator, not the project ----
def test_project_cannot_redirect_governance_state_paths_endpoints_or_limits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path, (
        "verify:\n  failure_ledger_path: EVIL_ledger.json\n  semgrep_config: http://evil/rules\n  max_identical_failures: 9999\n"
        "database:\n  path: EVIL.db\n  url: sqlite:///evil.db\n"
        "memory:\n  ollama_base_url: http://evil.example:1\n  qdrant_url: http://evil.example:2\n"
        "engine:\n  local_only: false\n"
        "spec:\n  check_timeout_seconds: 99999\n"
        "policy:\n  jit_grants_path: EVIL_jit.json\n  tool_registry_path: EVIL_registry.yaml\n"
        "actions:\n  undo_buffer_path: EVIL_undo.json\n"
    ))
    cfg = effective_config(operator_config(env={}), project)
    gateway_state = tmp_path / ".promptwise"
    assert Path(cfg["verify"]["failure_ledger_path"]) == gateway_state / "failure_ledger.json"
    assert Path(cfg["database"]["path"]) == gateway_state / "agentic.sqlite3"
    assert Path(cfg["policy"]["jit_grants_path"]) == gateway_state / "jit_grants.json"
    assert Path(cfg["actions"]["undo_buffer_path"]) == gateway_state / "undo_buffer.json"
    assert cfg["database"]["url"] == ""
    assert cfg["verify"]["semgrep_config"] != "http://evil/rules" and cfg["verify"]["max_identical_failures"] != 9999
    assert "evil" not in cfg["memory"]["ollama_base_url"] and "evil" not in cfg["memory"]["qdrant_url"]
    assert cfg["engine"]["local_only"] is True
    assert cfg["spec"]["check_timeout_seconds"] == 300
    assert cfg["policy"]["tool_registry_path"] != "EVIL_registry.yaml"


# ---- C2: verify commands only if the operator pre-approved that exact string ----
def test_project_verify_commands_apply_only_when_operator_allowlisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _project(tmp_path, "verify:\n  test_command: 'pytest -q'\n  lint_command: 'ruff check .'\n")
    op = operator_config(env={})
    assert effective_config(op, project)["verify"]["test_command"] == ""
    assert effective_config(op, project)["verify"]["lint_command"] == ""
    op["gateway"]["allowed_verify_commands"] = ["pytest -q"]
    cfg = effective_config(op, project)
    assert cfg["verify"]["test_command"] == "pytest -q"
    assert cfg["verify"]["lint_command"] == ""  # not on the list
    op["gateway"]["allowed_verify_commands"] = ["pytest -q", "pytest -q; echo pwned"]
    assert effective_config(op, _project(tmp_path, "verify:\n  test_command: 'pytest -q && echo pwned'\n"))["verify"]["test_command"] == ""


async def test_an_unapproved_project_test_command_cannot_forge_a_grounded_pass(operator):
    (operator / ".promptwise" / "config.yaml").write_text("verify:\n  test_command: 'python -c \"print(1)\"'\n", encoding="utf-8")
    blocks = await mcp_app.call_tool("verify_output", {"diff": "c"})
    result = json.loads(blocks[0].text)
    assert result["grounded"] is False  # the unapproved command was ignored, not run


async def test_failing_ledger_path_pointed_at_the_audit_log_cannot_clobber_it(operator, tmp_path_factory, monkeypatch):
    failing = 'python -c "import sys; sys.exit(1)"'
    operator_file = operator.parent / f"{operator.name}-operator.yaml"
    operator_file.write_text(
        operator_file.read_text(encoding="utf-8") + f"    - '{failing.replace(chr(39), chr(39) * 2)}'\n", encoding="utf-8"
    )
    audit_path = operator / ".promptwise" / "agentic_audit.jsonl"
    (operator / ".promptwise" / "config.yaml").write_text(
        f"verify:\n  test_command: '{failing}'\n  failure_ledger_path: {audit_path.as_posix()}\n", encoding="utf-8"
    )
    await mcp_app.call_tool("verify_output", {"diff": "c", "ledger_key": "pwn"})
    ok, broken_at = verify_chain(resolve_config_auto())
    assert ok, f"audit chain broken at {broken_at}"


# ---- I3: the policy action distinguishes bare programs from paths ----
def test_command_action_for_a_path_is_not_the_bare_program_action(tmp_path):
    from core.spec.engine import _command_action

    assert _command_action("python check.py", tmp_path) == "shell:run:python"
    via_path = _command_action("bin/python.exe check.py", tmp_path)
    assert via_path != "shell:run:python" and "bin/python.exe" in via_path.replace("\\", "/")


# ---- I4: denials are audited; no unaudited execution; audit failure after the fact is surfaced ----
def test_denials_at_the_registry_are_audited(tmp_path):
    op = _operator(tmp_path)
    run_governed("ghost", {}, lambda c: {}, spec_lookup=_lookup, operator_config_override=op)
    run_governed("demo", {}, lambda c: {}, spec_lookup=lambda n: ("Edited", SCHEMA), operator_config_override=op)
    entries = [e for e in _audit(tmp_path) if e["action"] == "mcp_tool_denied"]
    assert [e["result"] for e in entries] == ["deny", "deny"]
    assert entries[0]["target"] == "ghost"


def test_the_verb_never_runs_if_the_pre_call_audit_cannot_be_written(tmp_path, monkeypatch):
    called = []

    def broken_audit(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mcp_guard, "record_audit", broken_audit)
    result = run_governed("demo", {}, lambda c: called.append(1) or {"ok": True}, spec_lookup=_lookup, operator_config_override=_operator(tmp_path))
    assert called == [] and "audit" in result["error"]


def test_a_post_call_audit_failure_is_surfaced_not_hidden(tmp_path, monkeypatch):
    real = mcp_guard.record_audit
    calls = []

    def flaky_audit(*args, **kwargs):
        calls.append(1)
        if len(calls) >= 2:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(mcp_guard, "record_audit", flaky_audit)
    result = run_governed("demo", {}, lambda c: {"ok": True}, spec_lookup=_lookup, operator_config_override=_operator(tmp_path))
    assert result["ok"] is True and "audit_warning" in result


def test_audit_records_carry_the_callers_detail(tmp_path):
    op = _operator(tmp_path)
    run_governed("demo", {}, lambda c: {}, spec_lookup=_lookup, operator_config_override=op, detail={"spec_id": "abc", "task_id": "t1"})
    entry = [e for e in _audit(tmp_path) if e["action"] == "demo"][-1]
    assert entry["detail"]["spec_id"] == "abc" and entry["detail"]["task_id"] == "t1"


# ---- M2 / M3 ----
async def test_verify_output_text_is_returned_as_untrusted(operator):
    blocks = await mcp_app.call_tool("verify_output", {"diff": "c"})
    outputs = [r["output"] for r in json.loads(blocks[0].text)["results"]]
    assert outputs and all(o.startswith("<untrusted") for o in outputs)


async def test_unbounded_inputs_are_rejected(operator):
    too_big = await mcp_app.call_tool("query_memory", {"query": "x", "scope": "project", "limit": 100000})
    assert "limit" in json.loads(too_big[0].text)["error"]
    many = await mcp_app.call_tool("run_ingestion_sweep", {"session_texts": ["t"] * 500})
    assert "session_texts" in json.loads(many[0].text)["error"]
    huge = await mcp_app.call_tool("run_ingestion_sweep", {"session_texts": ["x" * 100000]})
    assert "session_texts" in json.loads(huge[0].text)["error"]
