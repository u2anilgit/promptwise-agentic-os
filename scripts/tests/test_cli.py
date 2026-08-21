from typer.testing import CliRunner

from scripts.promptwise import app

runner = CliRunner()


def test_doctor_exits_zero_when_no_failures():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "config.resolve" in result.stdout
    assert "PASS" in result.stdout


def test_doctor_lists_every_check():
    result = runner.invoke(app, ["doctor"])
    for name in ("hardware.ram", "config.resolve", "packs.integrity", "services.ollama"):
        assert name in result.stdout


def test_profile_writes_hardware_yaml(tmp_path, monkeypatch):
    out_path = tmp_path / "config" / "hardware_profile.yaml"
    result = runner.invoke(app, ["profile", "--out", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()
