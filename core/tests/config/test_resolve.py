from pathlib import Path
from core.config.resolve import resolve_config

def test_defaults_only():
    cfg = resolve_config()
    assert cfg["engine"]["name"] == "promptwise-agentic-os"
    assert cfg["engine"]["local_only"] is True

def test_org_overrides_defaults(tmp_path):
    org_file = tmp_path / "promptwise.config.yaml"
    org_file.write_text("engine:\n  local_only: false\n")
    cfg = resolve_config(org_path=org_file)
    assert cfg["engine"]["local_only"] is False
    assert cfg["engine"]["name"] == "promptwise-agentic-os"  # untouched key survives merge

def test_env_wins_over_everything(tmp_path, monkeypatch):
    org_file = tmp_path / "promptwise.config.yaml"
    org_file.write_text("engine:\n  local_only: false\n")
    cfg = resolve_config(org_path=org_file, env={"PROMPTWISE_ENGINE__LOCAL_ONLY": "true"})
    assert cfg["engine"]["local_only"] is True

def test_missing_optional_layers_are_skipped(tmp_path):
    cfg = resolve_config(
        org_path=tmp_path / "does-not-exist.yaml",
        project_path=tmp_path / "also-missing.yaml",
    )
    assert cfg["engine"]["name"] == "promptwise-agentic-os"
