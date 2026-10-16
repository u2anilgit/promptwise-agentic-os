import json
import os

import pytest

from core.policy.tool_pins import tool_description_hash
from gateway.mcp_guard import allowed_roots, confine, effective_config, run_governed

DESC, SCHEMA = "Demo tool", {"type": "object"}


def _lookup(name):
    return DESC, SCHEMA


def _operator(tmp_path, pin=True, enabled=True):
    registry = tmp_path / "tool_registry.yaml"
    pin_line = f"    description_sha256: '{tool_description_hash(DESC, SCHEMA)}'\n" if pin else ""
    registry.write_text(f"tools:\n  demo:\n    version: '1'\n    enabled: {str(enabled).lower()}\n{pin_line}", encoding="utf-8")
    allowed = tmp_path / "work"
    allowed.mkdir(exist_ok=True)
    return {
        "policy": {"tool_registry_path": str(registry), "default_effect": "deny"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "gateway": {"allowed_roots": [str(allowed)]},
        "paths": {"policies_dir": "OPERATOR_POLICIES"},
        "spec": {"allow_ungrounded": False, "enforce_command_policy": True, "allow_fileless_checks": False, "trivial_max_requirements": 1},
        "security": {"require_tool_pins": False},
    }


def _audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_allowed_roots_defaults_to_the_gateway_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert allowed_roots({}) == [tmp_path.resolve()]


def test_confine_accepts_inside_and_defaults_empty_to_the_first_root(tmp_path):
    op = _operator(tmp_path)
    work = (tmp_path / "work").resolve()
    (work / "sub").mkdir()
    assert confine(op, "") == work
    assert confine(op, str(work / "sub")) == work / "sub"


def test_confine_rejects_dotdot_and_foreign_absolute_paths(tmp_path):
    op = _operator(tmp_path)
    work = tmp_path / "work"
    assert confine(op, str(work / ".." / "..")) is None
    assert confine(op, str(tmp_path)) is None
    assert confine(op, os.path.abspath(os.sep)) is None


def test_confine_rejects_a_symlink_that_escapes(tmp_path):
    op = _operator(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "work" / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this machine")
    assert confine(op, str(link)) is None


def test_effective_config_forces_trusted_keys_from_the_operator(tmp_path):
    op = _operator(tmp_path)
    project = tmp_path / "work"
    (project / ".promptwise").mkdir()
    (project / ".promptwise" / "config.yaml").write_text(
        "spec:\n  allow_ungrounded: true\n  enforce_command_policy: false\n  allow_fileless_checks: true\n"
        "paths:\n  policies_dir: EVIL_POLICIES\n"
        "audit:\n  log_path: EVIL_AUDIT.jsonl\n"
        "policy:\n  default_effect: allow\n"
        "verify:\n  test_command: 'python -c \"pass\"'\n",
        encoding="utf-8",
    )
    cfg = effective_config(op, project)
    assert cfg["spec"]["allow_ungrounded"] is False
    assert cfg["spec"]["enforce_command_policy"] is True
    assert cfg["spec"]["allow_fileless_checks"] is False
    assert cfg["paths"]["policies_dir"] == "OPERATOR_POLICIES"
    assert cfg["audit"]["log_path"] == op["audit"]["log_path"]
    assert cfg["policy"]["default_effect"] == "deny"
    assert cfg["verify"]["test_command"] == 'python -c "pass"'  # non-trusted project keys survive


def test_governed_runs_the_body_and_audits_the_call(tmp_path):
    op = _operator(tmp_path)
    seen = {}

    def body(call):
        seen["root"] = call.root
        return {"ok": True}

    result = run_governed("demo", {"root": ""}, body, spec_lookup=_lookup, operator_config=op)
    assert result == {"ok": True}
    assert seen["root"] == (tmp_path / "work").resolve()
    entry = _audit(tmp_path)[-1]
    assert (entry["actor"], entry["action"], entry["result"]) == ("mcp", "demo", "allow")


def test_governed_denies_unregistered_disabled_and_mismatched_pin(tmp_path):
    called = []
    body = lambda call: called.append(1) or {}  # noqa: E731
    assert "error" in run_governed("ghost", {}, body, spec_lookup=_lookup, operator_config=_operator(tmp_path))
    assert "error" in run_governed("demo", {}, body, spec_lookup=_lookup, operator_config=_operator(tmp_path, enabled=False))
    stale = run_governed("demo", {}, body, spec_lookup=lambda n: ("Edited text", SCHEMA), operator_config=_operator(tmp_path))
    assert "changed since it was pinned" in stale["error"]
    assert called == []


def test_governed_denied_root_is_audited_and_the_body_never_runs(tmp_path):
    op = _operator(tmp_path)
    called = []
    result = run_governed("demo", {"root": str(tmp_path)}, lambda call: called.append(1) or {}, spec_lookup=_lookup, operator_config=op)
    assert "outside allowed roots" in result["error"]
    assert called == []
    entry = _audit(tmp_path)[-1]
    assert (entry["action"], entry["result"]) == ("mcp_root_denied", "deny")


def test_governed_value_error_becomes_an_error_dict(tmp_path):
    def body(call):
        raise ValueError("unknown spec 'x'")

    result = run_governed("demo", {}, body, spec_lookup=_lookup, operator_config=_operator(tmp_path))
    assert result == {"error": "unknown spec 'x'"}


def test_governed_unexpected_exception_is_an_internal_error_and_audited(tmp_path):
    def body(call):
        raise RuntimeError("secret detail that must not leak")

    result = run_governed("demo", {}, body, spec_lookup=_lookup, operator_config=_operator(tmp_path))
    assert result == {"error": "internal error: RuntimeError"}
    entry = _audit(tmp_path)[-1]
    assert (entry["action"], entry["result"]) == ("demo", "error")
