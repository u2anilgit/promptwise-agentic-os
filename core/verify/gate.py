# core/verify/gate.py
"""verify_output — docs/ARCHITECTURE.md §2, the mandatory verification
gate (CLAUDE.md goal 3). Runs tests + lint + Semgrep + Gitleaks against a
working tree, blocks until they pass, and tracks a failure ledger that
breaks an identical-failure retry loop after N attempts.

Does NOT apply `diff` to the working tree itself — `cwd` is assumed to
already reflect the change under review. `diff`/`spec` are carried through
for logging and as the failure ledger's signature source; a future phase's
LLM-based "diff-vs-spec self-review" leg is not implemented here (needs a
model-calling primitive that doesn't exist yet) — deliberately deferred.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_config_auto
from core.verify.ledger import record_failure, record_success
from core.verify.models import VerifyResult
from core.verify.runners import run_lint, run_tests
from core.verify.security import run_gitleaks, run_semgrep


def _signature(results: list) -> str:
    """A stable signature for 'the same failure' — used to detect an
    identical-failure retry loop. Based on which tools failed and their
    pass/fail shape, not full output text (output often contains
    timestamps/paths that vary run to run without the failure itself
    changing).
    """
    parts = [f"{r.tool}:{r.passed}" for r in results]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def verify_output(
    diff: str,
    spec: str | None = None,
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    ledger_key: str | None = None,
) -> VerifyResult:
    config = config if config is not None else resolve_config_auto()

    test_result = run_tests(config, cwd)
    lint_result = run_lint(config, cwd)
    semgrep_result = run_semgrep(config, cwd)
    gitleaks_result = run_gitleaks(config, cwd)

    results = [test_result, lint_result, semgrep_result, gitleaks_result]

    lint_blocks = bool(config.get("verify", {}).get("lint_blocks", False))
    blocking_failures = []
    if not test_result.passed:
        blocking_failures.append("tests failed")
    if lint_blocks and not lint_result.passed:
        blocking_failures.append("lint failed")
    if not semgrep_result.passed:
        blocking_failures.append("semgrep found blocking (error-severity) findings")
    if not gitleaks_result.passed:
        blocking_failures.append("gitleaks detected a secret")

    passed = len(blocking_failures) == 0
    blocked_reason = "; ".join(blocking_failures) if blocking_failures else None

    retry_loop_broken = False
    if ledger_key is not None:
        if passed:
            record_success(config, ledger_key)
        else:
            retry_loop_broken = record_failure(config, ledger_key, _signature(results))

    return VerifyResult(passed=passed, results=results, blocked_reason=blocked_reason, retry_loop_broken=retry_loop_broken)
