# core/tests/verify/test_security.py
import shutil
import subprocess

import pytest

from core.verify.security import run_gitleaks, run_semgrep


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


# --- Fix 1: gitleaks must not fail open on an unverified CLI contract -----


def test_run_gitleaks_exit_code_1_with_leaks_fails(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gitleaks")
    leaks_json = '[{"RuleID": "aws-access-key", "File": "leaked.py", "StartLine": 1}]'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, stdout=leaks_json))
    result = run_gitleaks({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is False
    assert len(result.findings) == 1


def test_run_gitleaks_nonzero_exit_with_unparseable_output_fails_not_crashes(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gitleaks")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(2, stdout="", stderr="fatal: bad config"))
    result = run_gitleaks({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is False


def test_run_gitleaks_exit_code_0_with_empty_json_passes(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gitleaks")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0, stdout="[]"))
    result = run_gitleaks({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is True


# --- Fix 2: semgrep must not discard returncode/errors --------------------


def test_run_semgrep_config_error_exit_code_fails(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(2, stdout="", stderr="invalid rule config"))
    result = run_semgrep({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is False


def test_run_semgrep_populated_errors_array_fails_even_with_empty_results(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/semgrep")
    body = '{"results": [], "errors": [{"message": "rule load failure"}]}'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0, stdout=body))
    result = run_semgrep({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is False


def test_run_semgrep_exit_code_1_with_findings_only_reports_findings(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/semgrep")
    body = '{"results": [{"extra": {"severity": "ERROR", "message": "boom"}, "path": "x.py", "start": {"line": 1}}], "errors": []}'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, stdout=body))
    result = run_semgrep({"verify": {}}, None)
    assert result.ran is True
    assert result.passed is False
    assert len(result.findings) == 1
