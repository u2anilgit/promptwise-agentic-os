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


def test_pack_list_reports_no_packs_when_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "packs" / "installed").mkdir(parents=True)
    result = runner.invoke(app, ["pack", "list"])
    assert result.exit_code == 0
    assert "no packs installed" in result.stdout


def test_pack_install_then_list_then_remove(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry_pack = tmp_path / "packs" / "registry" / "sample-pack"
    registry_pack.mkdir(parents=True)
    (registry_pack / "pack.yaml").write_text(
        "name: sample-pack\n"
        "version: 1.0.0\n"
        "kind: intelligence\n"
        "summary: test pack\n"
        'requires_core: ">=0.0.0,<1.0.0"\n'
        "permissions_rationale: none needed\n",
        encoding="utf-8",
    )

    install_result = runner.invoke(app, ["pack", "install", "sample-pack"])
    assert install_result.exit_code == 0
    assert "installed sample-pack@1.0.0" in install_result.stdout

    list_result = runner.invoke(app, ["pack", "list"])
    assert list_result.exit_code == 0
    assert "sample-pack@1.0.0" in list_result.stdout
    assert "intelligence" in list_result.stdout

    remove_result = runner.invoke(app, ["pack", "remove", "sample-pack"])
    assert remove_result.exit_code == 0
    assert "removed sample-pack" in remove_result.stdout

    list_after_remove = runner.invoke(app, ["pack", "list"])
    assert "no packs installed" in list_after_remove.stdout


def test_pack_install_unknown_pack_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["pack", "install", "does-not-exist"])
    assert result.exit_code == 1
    assert "install failed" in result.stdout


def test_pack_remove_unknown_pack_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["pack", "remove", "never-installed"])
    assert result.exit_code == 1
    assert "not installed" in result.stdout
