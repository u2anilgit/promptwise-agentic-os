# core/tests/verify/test_security.py
import shutil

import pytest

from core.verify.security import run_gitleaks, run_semgrep


def test_run_semgrep_skips_gracefully_when_binary_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = run_semgrep({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


def test_run_gitleaks_skips_gracefully_when_binary_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = run_gitleaks({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep not installed in this environment")
def test_run_semgrep_actually_runs_when_installed(tmp_path):
    (tmp_path / "clean.py").write_text("x = 1\n")
    result = run_semgrep({"verify": {"semgrep_config": "auto"}}, tmp_path)
    assert result.ran is True
    assert result.tool == "semgrep"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed in this environment")
def test_run_gitleaks_detects_a_planted_secret(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    (tmp_path / "leaked.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    result = run_gitleaks({"verify": {}}, tmp_path)
    assert result.ran is True
    assert result.passed is False
    assert len(result.findings) > 0
