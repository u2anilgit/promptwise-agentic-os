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
    assert "events 1" in report.stdout and "cloud-premium" in report.stdout and "per task" in report.stdout


def test_usage_record_rejects_bad_input_with_exit_2(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["usage", "record", "--tier", "nope", "--tokens-in", "1", "--tokens-out", "1"])
    assert result.exit_code == 2 and "unknown tier" in result.stdout
