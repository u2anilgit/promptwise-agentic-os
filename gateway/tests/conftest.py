import pytest


@pytest.fixture
def operator(tmp_path, monkeypatch):
    """A gateway 'operator' environment: cwd = tmp_path with its own tool registry
    (every live MCP tool enabled + pinned), a policy allowing `python`, an
    operator config (PROMPTWISE_OPERATOR_CONFIG) that pre-approves the verify
    command `python -c "pass"` and points Ollama/Qdrant at a closed port so memory
    verbs exercise their degraded paths fast."""
    from core.config.resolve import resolve_config_auto
    from core.policy.tool_pins import write_pins
    from gateway.mcp_server import live_tool_specs

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text("verify:\n  test_command: ''\n  lint_command: ''\n", encoding="utf-8")
    operator_file = tmp_path.parent / f"{tmp_path.name}-operator.yaml"
    operator_file.write_text(
        "memory:\n  qdrant_url: http://127.0.0.1:9\n  ollama_base_url: http://127.0.0.1:9\n"
        "gateway:\n  allowed_verify_commands:\n    - 'python -c \"pass\"'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMPTWISE_OPERATOR_CONFIG", str(operator_file))
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "allow.yaml").write_text(
        "rules:\n  - action: 'shell:run:python'\n    effect: allow\n", encoding="utf-8"
    )
    specs = live_tool_specs()
    (tmp_path / "tool_registry.yaml").write_text(
        "tools:\n" + "".join(f"  {name}:\n    version: '1'\n    enabled: true\n" for name in specs), encoding="utf-8"
    )
    write_pins(resolve_config_auto(), specs)
    return tmp_path
