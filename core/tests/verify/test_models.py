from core.verify.models import ToolRunResult, VerifyFinding, VerifyResult


def test_verify_finding_defaults():
    finding = VerifyFinding(tool="semgrep", severity="error", message="hardcoded secret")
    assert finding.file is None
    assert finding.line is None


def test_tool_run_result_defaults_to_no_findings():
    result = ToolRunResult(tool="pytest", ran=True, passed=True, output="5 passed")
    assert result.findings == []


def test_verify_result_defaults():
    result = VerifyResult(passed=True, results=[])
    assert result.blocked_reason is None
    assert result.retry_loop_broken is False
