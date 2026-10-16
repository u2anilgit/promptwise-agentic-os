import json

from gateway.mcp_server import live_tool_specs, mcp_app

REQS = ["The system shall log in users.", "The system shall log out users."]
TASKS = [
    {"id": "t1", "requirement_ids": ["R1"]},
    {"id": "t2", "requirement_ids": ["R2"], "depends_on": ["t1"]},
]
CHECKS = [
    {"requirement_id": "R1", "command": "python check_login.py", "files": ["check_login.py"]},
    {"requirement_id": "R2", "command": "python check_logout.py", "files": ["check_logout.py"]},
]


async def _call(name, args):
    blocks = await mcp_app.call_tool(name, args)
    return json.loads(blocks.content[0].text)


def _project(operator, test_command='python -c "pass"', extra=""):
    (operator / "check_login.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (operator / "check_logout.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (operator / ".promptwise" / "config.yaml").write_text(
        "memory:\n  qdrant_url: http://127.0.0.1:9\n  ollama_base_url: http://127.0.0.1:9\n"
        f"verify:\n  test_command: '{test_command}'\n  lint_command: ''\n{extra}",
        encoding="utf-8",
    )


async def _tasked(operator):
    spec = await _call("specify_feature", {"request": "login", "requirements": REQS})
    sid = spec["spec_id"]
    await _call("plan_feature", {"spec_id": sid, "approach": "do it"})
    tasks = await _call("tasks_feature", {"spec_id": sid, "tasks": TASKS, "checks": CHECKS})
    assert "error" not in tasks, tasks
    return sid


async def test_full_spec_lifecycle_over_mcp(operator):
    _project(operator)
    sid = await _tasked(operator)
    for tid in ("t1", "t2"):
        done = await _call("complete_task", {"spec_id": sid, "task_id": tid, "evidence": "implemented"})
        assert done["accepted"] is True, done
    assert (await _call("verify_feature", {"spec_id": sid}))["verified"] is True
    report = await _call("converge_feature", {"spec_id": sid})
    assert report["stale"] is False and report["done_tasks"] == 2


async def test_complete_task_is_denied_by_the_operators_policy_until_allowed(operator):
    _project(operator)
    sid = await _tasked(operator)
    policy = operator / "policies" / "allow.yaml"
    policy.write_text("rules: []\n", encoding="utf-8")
    denied = await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    assert denied["accepted"] is False and denied["reasons"] == ["policy_denied:R1"]
    policy.write_text("rules:\n  - action: 'shell:run:python'\n    effect: allow\n", encoding="utf-8")
    assert (await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"}))["accepted"] is True


async def test_a_project_cannot_enable_ungrounded_verification_via_its_own_config(operator):
    _project(operator, test_command="", extra="spec:\n  allow_ungrounded: true\n  enforce_command_policy: false\n")
    sid = await _tasked(operator)
    result = await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    assert result["accepted"] is False and "ungrounded_verification" in result["reasons"]


async def test_tasks_over_mcp_cannot_carry_a_run_callable_or_unknown_keys(operator):
    _project(operator)
    spec = await _call("specify_feature", {"request": "login", "requirements": REQS})
    await _call("plan_feature", {"spec_id": spec["spec_id"], "approach": "x"})
    for bad in ({"id": "t1", "requirement_ids": ["R1"], "run": "print(1)"}, {"id": "t1", "requirement_ids": ["R1"], "surprise": 1}):
        result = await _call("tasks_feature", {"spec_id": spec["spec_id"], "tasks": [bad], "checks": CHECKS})
        assert "error" in result


async def test_spec_verbs_return_errors_not_transport_failures(operator):
    for name, args in (
        ("plan_feature", {"spec_id": "ghost", "approach": "a"}),
        ("verify_feature", {"spec_id": "ghost"}),
        ("converge_feature", {"spec_id": "ghost"}),
        ("complete_task", {"spec_id": "ghost", "task_id": "t", "evidence": "e"}),
    ):
        assert "unknown spec" in (await _call(name, args))["error"]


async def test_amend_check_over_mcp_reopens_work_and_is_audited(operator):
    _project(operator)
    sid = await _tasked(operator)
    await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    (operator / "check_login.py").write_text("import sys\nsys.exit(0)  # revised\n", encoding="utf-8")
    amended = await _call("amend_check", {
        "spec_id": sid, "requirement_id": "R1", "command": "python check_login.py",
        "files": ["check_login.py"], "reason": "login flow revised",
    })
    assert amended["file_hashes"]["check_login.py"]
    assert (await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"}))["accepted"] is True


async def test_spec_tools_are_registered_enabled_and_pinned(operator):
    from core.config.resolve import resolve_config_auto
    from core.policy.tool_pins import tool_description_hash
    from core.policy.tool_registry import load_tool_registry

    registry = load_tool_registry(resolve_config_auto())
    specs = live_tool_specs()
    expected = {"specify_feature", "plan_feature", "tasks_feature", "complete_task", "verify_feature", "converge_feature", "amend_check"}
    assert expected <= set(specs)
    for name, (desc, schema) in specs.items():
        assert registry[name].enabled and registry[name].description_sha256 == tool_description_hash(desc, schema), name
