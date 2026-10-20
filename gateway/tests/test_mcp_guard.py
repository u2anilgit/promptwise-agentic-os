import json
import os

import pytest

from core.policy.tool_pins import tool_description_hash
from gateway.mcp_guard import allowed_roots, confine, operator_config, run_governed

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


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_confine_rejects_a_junction_that_escapes(tmp_path):
    """Junctions need no privilege, so this gives the escape check real coverage on Windows."""
    import subprocess

    op = _operator(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "work" / "junction"
    assert subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True).returncode == 0
    assert confine(op, str(link)) is None
    assert confine(op, str(link / "sub")) is None


def test_governed_runs_the_body_and_audits_the_call(tmp_path):
    op = _operator(tmp_path)
    seen = {}

    def body(call):
        seen["root"] = call.root
        return {"ok": True}

    result = run_governed("demo", {"root": ""}, body, spec_lookup=_lookup, operator_config_override=op)
    assert result == {"ok": True}
    assert seen["root"] == (tmp_path / "work").resolve()
    entry = _audit(tmp_path)[-1]
    assert (entry["actor"], entry["action"], entry["result"]) == ("mcp", "demo", "allow")


def test_governed_denies_unregistered_disabled_and_mismatched_pin(tmp_path):
    called = []
    body = lambda call: called.append(1) or {}  # noqa: E731
    assert "error" in run_governed("ghost", {}, body, spec_lookup=_lookup, operator_config_override=_operator(tmp_path))
    assert "error" in run_governed("demo", {}, body, spec_lookup=_lookup, operator_config_override=_operator(tmp_path, enabled=False))
    stale = run_governed("demo", {}, body, spec_lookup=lambda n: ("Edited text", SCHEMA), operator_config_override=_operator(tmp_path))
    assert "changed since it was pinned" in stale["error"]
    assert called == []


def test_governed_denied_root_is_audited_and_the_body_never_runs(tmp_path):
    op = _operator(tmp_path)
    called = []
    result = run_governed("demo", {"root": str(tmp_path)}, lambda call: called.append(1) or {}, spec_lookup=_lookup, operator_config_override=op)
    assert "outside allowed roots" in result["error"]
    assert called == []
    entry = _audit(tmp_path)[-1]
    assert (entry["action"], entry["result"]) == ("mcp_root_denied", "deny")


def test_governed_value_error_becomes_an_error_dict(tmp_path):
    def body(call):
        raise ValueError("unknown spec 'x'")

    result = run_governed("demo", {}, body, spec_lookup=_lookup, operator_config_override=_operator(tmp_path))
    assert result == {"error": '<untrusted source="error">\nunknown spec \'x\'\n</untrusted>'}  # may echo caller input


def test_governed_unexpected_exception_is_an_internal_error_and_audited(tmp_path):
    def body(call):
        raise RuntimeError("secret detail that must not leak")

    result = run_governed("demo", {}, body, spec_lookup=_lookup, operator_config_override=_operator(tmp_path))
    assert result == {"error": "internal error: RuntimeError"}
    entry = _audit(tmp_path)[-1]
    assert (entry["action"], entry["result"]) == ("demo", "error")


def test_operator_config_ignores_the_projects_own_config_layers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text("spec:\n  allow_ungrounded: true\n", encoding="utf-8")
    (tmp_path / "promptwise.config.yaml").write_text("spec:\n  allow_ungrounded: true\n", encoding="utf-8")
    assert operator_config(env={})["spec"]["allow_ungrounded"] is False


def test_operator_config_reads_the_operator_file_and_environment(tmp_path):
    operator_file = tmp_path / "operator.yaml"
    operator_file.write_text("gateway:\n  allowed_roots: ['/srv/projects']\n", encoding="utf-8")
    cfg = operator_config(env={"PROMPTWISE_OPERATOR_CONFIG": str(operator_file), "PROMPTWISE_SPEC__ALLOW_UNGROUNDED": "true"})
    assert cfg["gateway"]["allowed_roots"] == ["/srv/projects"]
    assert cfg["spec"]["allow_ungrounded"] is True  # the operator's own environment may loosen it
