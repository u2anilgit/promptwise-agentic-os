from core.policy.engine import check_policy, load_policy


def _config(tmp_path, rules_yaml: str):
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "test.yaml").write_text(rules_yaml)
    return {"paths": {"policies_dir": str(policies_dir)}, "policy": {"default_effect": "deny"}}


def test_load_policy_reads_rules_from_the_configured_dir(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.*\n    effect: allow\n")
    rules = load_policy(config)
    assert len(rules) == 1
    assert rules[0].action == "fs.write.*"
    assert rules[0].effect == "allow"


def test_check_policy_allows_a_matching_allow_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.*\n    effect: allow\n")
    decision = check_policy("fs.write.config", config=config)
    assert decision.allowed is True
    assert decision.matched_rule == "fs.write.*"


def test_check_policy_denies_a_matching_deny_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.secrets/*\n    effect: deny\n")
    decision = check_policy("fs.write.secrets/apikey", config=config)
    assert decision.allowed is False


def test_check_policy_defaults_to_deny_with_no_matching_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.read.*\n    effect: allow\n")
    decision = check_policy("shell.exec.rm", config=config)
    assert decision.allowed is False
    assert decision.matched_rule is None
    assert "default" in decision.reason.lower()


def test_check_policy_first_match_wins(tmp_path):
    config = _config(
        tmp_path,
        "rules:\n"
        "  - action: fs.write.*\n"
        "    effect: deny\n"
        "  - action: fs.write.*\n"
        "    effect: allow\n",
    )
    decision = check_policy("fs.write.anything", config=config)
    assert decision.allowed is False  # first matching rule (deny) wins


def test_check_policy_default_effect_can_be_configured_to_allow(tmp_path):
    config = _config(tmp_path, "rules: []\n")
    config["policy"]["default_effect"] = "allow"
    decision = check_policy("anything.at.all", config=config)
    assert decision.allowed is True


def test_missing_policies_dir_falls_back_to_default_deny_without_crashing(tmp_path):
    config = {"paths": {"policies_dir": str(tmp_path / "does-not-exist")}, "policy": {"default_effect": "deny"}}
    decision = check_policy("fs.write.x", config=config)
    assert decision.allowed is False
