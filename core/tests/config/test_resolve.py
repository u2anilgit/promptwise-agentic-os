from pathlib import Path
import pytest
from core.config.resolve import resolve_config, discover_config_paths, resolve_config_auto

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


def test_discover_config_paths_returns_conventional_locations(tmp_path):
    org, project, local = discover_config_paths(tmp_path)
    assert org == tmp_path / "promptwise.config.yaml"
    assert project == tmp_path / ".promptwise" / "config.yaml"
    assert local == tmp_path / ".promptwise" / "local.yaml"


def test_resolve_config_auto_finds_org_file(tmp_path):
    (tmp_path / "promptwise.config.yaml").write_text("engine:\n  local_only: false\n")
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["engine"]["local_only"] is False
    assert cfg["engine"]["name"] == "promptwise-agentic-os"


def test_resolve_config_auto_finds_project_and_local_files(tmp_path):
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text("routing:\n  default_tier: local-large\n")
    (tmp_path / ".promptwise" / "local.yaml").write_text("routing:\n  default_tier: cloud-cheap\n")
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["routing"]["default_tier"] == "cloud-cheap"  # local overrides project


def test_resolve_config_auto_with_no_files_returns_defaults(tmp_path):
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["engine"]["name"] == "promptwise-agentic-os"


def test_missing_system_defaults_raises(monkeypatch, tmp_path):
    import core.config.resolve as resolve_module

    fake_defaults = tmp_path / "does-not-exist.yaml"
    monkeypatch.setattr(resolve_module, "DEFAULTS_PATH", fake_defaults)
    with pytest.raises(FileNotFoundError):
        resolve_module.resolve_config()
