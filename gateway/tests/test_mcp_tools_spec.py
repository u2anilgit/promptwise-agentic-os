import json

from gateway.mcp_server import live_tool_specs, mcp_app

REQS = ["The system shall log in users.", "The system shall log out users."]
TASKS = [
    {"id": "t1", "requirement_ids": ["R1"]},
    {"id": "t2", "requirement_ids": ["R2"], "depends_on": ["t1"]},
]
CHECKS = [
    {"requirement_id": "R1", "command": "python check_login.py", "files": ["check_login.py"], "expect_baseline": "pass"},
    {"requirement_id": "R2", "command": "python check_logout.py", "files": ["check_logout.py"], "expect_baseline": "pass"},
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
    args = {
        "spec_id": sid, "requirement_id": "R1", "command": "python check_login.py",
        "files": ["check_login.py"], "reason": "login flow revised", "expect_baseline": "pass",
    }
    assert "grant" in (await _call("amend_check", args))["error"]  # an agent cannot amend unattended
    from core.policy.jit import grant_jit_permission
    from core.spec.engine import amend_grant_scope
    from gateway.mcp_guard import operator_config, pinned_config

    grant_jit_permission(pinned_config(operator_config()), amend_grant_scope(sid), 300)
    amended = await _call("amend_check", args)
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


def _red_check(operator):
    (operator / "check_a.py").write_text("import sys, pathlib\nsys.exit(0 if pathlib.Path('a.done').exists() else 1)\n", encoding="utf-8")
    (operator / ".promptwise" / "config.yaml").write_text("verify:\n  test_command: 'python -c \"pass\"'\n", encoding="utf-8")


def _append_operator(operator, text):
    path = operator.parent / f"{operator.name}-operator.yaml"
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


async def _red_task(operator):
    _red_check(operator)
    spec = await _call("specify_feature", {"request": "a", "requirements": ["The system shall do A."]})
    sid = spec["spec_id"]
    await _call("plan_feature", {"spec_id": sid, "approach": "x"})
    made = await _call("tasks_feature", {
        "spec_id": sid, "tasks": [{"id": "t1", "requirement_ids": ["R1"]}],
        "checks": [{"requirement_id": "R1", "command": "python check_a.py", "files": ["check_a.py"]}],
    })
    assert "error" not in made, made  # default expect_baseline is "fail": the check is genuinely red
    (operator / "a.done").write_text("x", encoding="utf-8")
    return sid


async def test_a_vacuous_check_is_refused_over_mcp(operator):
    (operator / "check_a.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    spec = await _call("specify_feature", {"request": "a", "requirements": ["The system shall do A."]})
    await _call("plan_feature", {"spec_id": spec["spec_id"], "approach": "x"})
    result = await _call("tasks_feature", {
        "spec_id": spec["spec_id"], "tasks": [{"id": "t1", "requirement_ids": ["R1"]}],
        "checks": [{"requirement_id": "R1", "command": "python check_a.py", "files": ["check_a.py"]}],
    })
    assert "already passes before implementation" in result["error"]


async def test_reviewer_notes_come_back_wrapped_as_untrusted(operator):
    (operator / "reject.py").write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': False, 'reasons': ['missing empty-input case']}))\n", encoding="utf-8")
    _append_operator(operator, "verify:\n  reviewer_command: 'python reject.py'\n")
    sid = await _red_task(operator)
    result = await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    assert result["accepted"] is False and result["reasons"] == ["reviewer_rejected"]
    assert result["notes"][0].startswith('<untrusted source="reviewer">') and "missing empty-input case" in result["notes"][0]


async def test_a_project_cannot_supply_its_own_reviewer_when_the_operator_requires_one(operator):
    _append_operator(operator, "spec:\n  require_reviewer: true\n")
    (operator / "approve.py").write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': True}))\n", encoding="utf-8")
    sid = await _red_task(operator)
    (operator / ".promptwise" / "config.yaml").write_text(
        "verify:\n  test_command: 'python -c \"pass\"'\n  reviewer_command: 'python approve.py'\n", encoding="utf-8"
    )
    result = await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    assert result["accepted"] is False and result["reasons"] == ["reviewer_not_configured"]


async def test_the_operators_reviewer_wins_over_a_project_supplied_one(operator):
    (operator / "reject.py").write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': False, 'reasons': ['no']}))\n", encoding="utf-8")
    (operator / "approve.py").write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': True}))\n", encoding="utf-8")
    _append_operator(operator, "verify:\n  reviewer_command: 'python reject.py'\n")
    sid = await _red_task(operator)
    (operator / ".promptwise" / "config.yaml").write_text(
        "verify:\n  test_command: 'python -c \"pass\"'\n  reviewer_command: 'python approve.py'\n", encoding="utf-8"
    )
    result = await _call("complete_task", {"spec_id": sid, "task_id": "t1", "evidence": "e"})
    assert result["accepted"] is False and result["reasons"] == ["reviewer_rejected"]
