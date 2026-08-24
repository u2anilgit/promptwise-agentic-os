from core.policy.tool_registry import is_tool_allowed, load_tool_registry


def _config(tmp_path, registry_yaml: str):
    path = tmp_path / "tool_registry.yaml"
    path.write_text(registry_yaml)
    return {"policy": {"tool_registry_path": str(path)}}


def test_load_tool_registry_reads_entries(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    registry = load_tool_registry(config)
    assert "verify_output" in registry
    assert registry["verify_output"].enabled is True


def test_is_tool_allowed_true_for_an_enabled_registered_tool(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    assert is_tool_allowed(config, "verify_output") is True


def test_is_tool_allowed_false_for_an_unregistered_tool(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    assert is_tool_allowed(config, "some_unpinned_tool") is False


def test_is_tool_allowed_false_when_kill_switched(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: false\n")
    assert is_tool_allowed(config, "verify_output") is False


def test_missing_registry_file_denies_everything_without_crashing(tmp_path):
    config = {"policy": {"tool_registry_path": str(tmp_path / "does-not-exist.yaml")}}
    assert is_tool_allowed(config, "verify_output") is False
