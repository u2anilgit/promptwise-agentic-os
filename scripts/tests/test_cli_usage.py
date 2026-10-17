from typer.testing import CliRunner

from scripts.promptwise import app

runner = CliRunner()


def _env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPTWISE_DATABASE__PATH", str(tmp_path / "u.sqlite3"))
    monkeypatch.setenv("PROMPTWISE_AUDIT__LOG_PATH", str(tmp_path / "audit.jsonl"))


def test_usage_record_then_report(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    rec = runner.invoke(app, ["usage", "record", "--tier", "cloud-premium", "--tokens-in", "1000", "--tokens-out", "500", "--agent", "cli", "--task-ref", "T-1"])
    assert rec.exit_code == 0, rec.stdout
    report = runner.invoke(app, ["usage", "report"])
    assert report.exit_code == 0
    assert "events 1" in report.stdout and "cloud-premium" in report.stdout and "per referenced task" in report.stdout


def test_usage_record_rejects_bad_input_with_exit_2(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["usage", "record", "--tier", "nope", "--tokens-in", "1", "--tokens-out", "1"])
    assert result.exit_code == 2 and "unknown tier" in result.stdout


def test_cli_uses_the_operator_database_not_a_project_layer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROMPTWISE_DATABASE__PATH", raising=False)
    monkeypatch.setenv("PROMPTWISE_AUDIT__LOG_PATH", str(tmp_path / "audit.jsonl"))
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text("database:\n  path: elsewhere.sqlite3\n", encoding="utf-8")
    result = runner.invoke(app, ["usage", "record", "--tier", "local-small", "--tokens-in", "1", "--tokens-out", "1"])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".promptwise" / "agentic.sqlite3").exists()
    assert not (tmp_path / "elsewhere.sqlite3").exists()
