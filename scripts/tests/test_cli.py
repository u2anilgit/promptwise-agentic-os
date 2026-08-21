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


def test_doctor_exits_one_when_a_check_fails(monkeypatch):
    import scripts.promptwise as promptwise_module
    from core.diagnostics.models import CheckResult

    def _broken_diagnostics(config=None):
        return [CheckResult(name="hardware.ram", status="FAIL", message="simulated failure for test")]

    monkeypatch.setattr(promptwise_module.diagnostics_checks, "run_diagnostics", _broken_diagnostics)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout
