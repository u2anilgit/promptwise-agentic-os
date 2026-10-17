from typer.testing import CliRunner

from scripts.promptwise import app

runner = CliRunner()


def test_dashboard_credential_command_prints_a_stable_value(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "cred"))
    first = runner.invoke(app, ["dashboard", "token"])
    second = runner.invoke(app, ["dashboard", "token"])
    assert first.exit_code == 0 and second.exit_code == 0
    value = first.stdout.strip().splitlines()[-1]
    assert len(value) >= 32
    assert second.stdout.strip().splitlines()[-1] == value
    assert (tmp_path / "cred").read_text(encoding="utf-8").strip() == value
