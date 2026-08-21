# Phase 3 — Governed System Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the governance layer `docs/ARCHITECTURE.md` calls the "Action layer": `check_policy` with a real enforcement point, JIT permission grants with TTL expiry, a hash-chained audit log, an undo buffer for reversible filesystem actions, an MCP tool allowlist with a kill switch, a redacted support-bundle generator, and `promptwise upgrade --dry-run` — the `docs/ROADMAP.md` Phase 3 row.

**Architecture:** Three new core packages — `core/audit/` (the hash-chained log everything else in this phase writes to), `core/policy/` (`check_policy`, JIT grants, the MCP tool registry — all pure decision logic, config/file-backed, no DB), `core/actions/` (the one governed action verb this phase ships: `fs_write`, gated by policy, logged to audit, undo-buffered). `core/models/` + `core/migrations/` introduce this project's first SQLAlchemy/Alembic usage — minimal, just enough to make `promptwise upgrade --dry-run` real, not a full ORM migration of everything built so far (nothing else in this phase needs a database; audit/policy/JIT all stay file-backed, same tier of durability as Phase 2's failure ledger). Every new file/directory path is config-resolved via `resolve_path` (Phase 1's fix-wave helper) — never hardcoded.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2.0 + Alembic (new to this phase, `CLAUDE.md`'s locked stack), PyYAML. No new external services — audit/policy/JIT/undo all stay JSON/JSONL-file-backed; the DB is used only for a `schema_version` table `upgrade --dry-run` reads.

**Spec:** `docs/ROADMAP.md` (Phase 3 row), `docs/ARCHITECTURE.md` §2 (Action layer, tool registry), `docs/MAINTENANCE.md` §2 (`policy.load`/`audit.chain` doctor checks — already stubbed WARN in Phase 0, this phase makes them real), §3 (support bundle), §5 (upgrade & rollback), `core/CLAUDE.md` (`policy/`, `audit/` package layout).

## Global Constraints

- No domain-specific logic in `core/` or `gateway/` (root `CLAUDE.md` goal 1).
- Every core function reads config only through `core/config/resolve.py` (`resolve_config_auto`/`resolve_path`) — never `open()` a config/policy/log file elsewhere.
- Every core function is covered by a failing-test-first cycle (`superpowers:test-driven-development`).
- Zero cloud calls, zero paid services.
- **Default-deny**: `policy.default_effect: deny` (already in `defaults.yaml` since Phase 2) means any action with no matching rule is denied, not allowed — this phase must not weaken that default.
- The undo buffer and audit log must never be bypassable by a caller — `fs_write` (this phase's one governed action) always goes through `check_policy` → audit → undo-buffer, in that order, with no shortcut.
- Redaction (support bundle) is a single shared utility (`core/diagnostics/redact.py`) — one implementation, not two, per `MAINTENANCE.md` §3.
- Conventional Commits, no AI-attribution trailers.

---

### Task 1: Hash-chained audit log

**Files:**
- Create: `core/audit/__init__.py`
- Create: `core/audit/models.py`
- Create: `core/audit/log.py`
- Modify: `core/config/defaults.yaml`
- Modify: `core/diagnostics/checks.py` (make `audit.chain` real, was stubbed WARN)
- Test: `core/tests/audit/__init__.py`
- Test: `core/tests/audit/test_log.py`
- Test: `core/tests/diagnostics/test_checks.py` (append)

**Interfaces:**
- Consumes: `resolve_path`, `resolve_config_auto` (Phase 1).
- Produces: `AuditRecord(BaseModel)` (id: str, timestamp: str, actor: str, action: str, target: str, result: Literal["allow","deny","error"], detail: dict, prev_hash: str, hash: str), `record_audit(config: dict, actor: str, action: str, target: str, result: str, detail: dict | None = None) -> AuditRecord`, `verify_chain(config: dict) -> tuple[bool, int | None]` (`(True, None)` if the chain is unbroken, `(False, index)` naming the first broken link). Tasks 2-5 all call `record_audit` after every policy decision/JIT grant/tool-registry check/`fs_write`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/audit/__init__.py
```

```python
# core/tests/audit/test_log.py
from core.audit.log import record_audit, verify_chain


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def test_record_audit_returns_a_record_with_a_hash(tmp_path):
    config = _config(tmp_path)
    record = record_audit(config, actor="cli", action="fs_write", target="foo.txt", result="allow")
    assert record.hash
    assert record.prev_hash == "0" * 64  # genesis


def test_second_record_chains_to_the_first(tmp_path):
    config = _config(tmp_path)
    r1 = record_audit(config, actor="cli", action="fs_write", target="a.txt", result="allow")
    r2 = record_audit(config, actor="cli", action="fs_write", target="b.txt", result="allow")
    assert r2.prev_hash == r1.hash
    assert r2.hash != r1.hash


def test_verify_chain_passes_on_untampered_log(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="cli", action="a", target="x", result="allow")
    record_audit(config, actor="cli", action="b", target="y", result="deny")
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_verify_chain_detects_tampering(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="cli", action="a", target="x", result="allow")
    record_audit(config, actor="cli", action="b", target="y", result="allow")
    path = config["audit"]["log_path"]
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    import json

    tampered = json.loads(lines[0])
    tampered["target"] = "tampered"
    lines[0] = json.dumps(tampered) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    ok, broken_at = verify_chain(config)
    assert ok is False
    assert broken_at == 0


def test_verify_chain_on_empty_or_missing_log_is_clean(tmp_path):
    config = _config(tmp_path)
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_record_audit_result_must_be_one_of_the_allowed_values(tmp_path):
    import pytest
    from pydantic import ValidationError

    config = _config(tmp_path)
    with pytest.raises(ValidationError):
        record_audit(config, actor="cli", action="a", target="x", result="not-a-real-result")
```

```python
# core/tests/diagnostics/test_checks.py — append
def test_audit_chain_check_passes_on_a_clean_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.audit.log import record_audit
    from core.diagnostics.checks import _check_audit_chain

    config = {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}
    record_audit(config, actor="cli", action="a", target="x", result="allow")
    result = _check_audit_chain(config)
    assert result.status == "PASS"


def test_audit_chain_check_warns_not_fails_on_missing_log(tmp_path):
    from core.diagnostics.checks import _check_audit_chain

    config = {"audit": {"log_path": str(tmp_path / "does-not-exist.jsonl")}}
    result = _check_audit_chain(config)
    assert result.status in ("PASS", "WARN")  # no log yet is a valid, non-broken state
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/audit/test_log.py core/tests/diagnostics/test_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.audit'`

- [ ] **Step 3: Write `core/audit/__init__.py`** (empty package marker)

- [ ] **Step 4: Write `core/audit/models.py`**

```python
# core/audit/models.py
from typing import Any, Literal

from pydantic import BaseModel

AuditResult = Literal["allow", "deny", "error"]


class AuditRecord(BaseModel):
    id: str
    timestamp: str
    actor: str
    action: str
    target: str
    result: AuditResult
    detail: dict[str, Any] = {}
    prev_hash: str
    hash: str
```

- [ ] **Step 5: Write `core/audit/log.py`**

```python
# core/audit/log.py
"""Hash-chained audit log — docs/ARCHITECTURE.md §2, docs/MAINTENANCE.md §2
(the audit.chain doctor check). Append-only JSONL, config-resolved path
(same resolve_path pattern as Phase 1/2's other file-backed stores). Each
record's hash covers the previous record's hash, so tampering with any
record breaks every hash after it — verify_chain walks the file and
reports the first break.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.audit.models import AuditRecord
from core.config.resolve import resolve_path

GENESIS_HASH = "0" * 64


def _log_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "audit.log_path", ".promptwise/audit.jsonl")


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    canonical = json.dumps(record_without_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    last_line = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last_line = line
    if last_line is None:
        return GENESIS_HASH
    return json.loads(last_line)["hash"]


def record_audit(
    config: dict[str, Any],
    actor: str,
    action: str,
    target: str,
    result: str,
    detail: dict[str, Any] | None = None,
) -> AuditRecord:
    path = _log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _last_hash(path)

    body = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "target": target,
        "result": result,
        "detail": detail or {},
        "prev_hash": prev_hash,
    }
    record_hash = _record_hash(body)
    record = AuditRecord(**body, hash=record_hash)

    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")

    return record


def verify_chain(config: dict[str, Any]) -> tuple[bool, int | None]:
    path = _log_path(config)
    if not path.exists():
        return True, None

    prev_hash = GENESIS_HASH
    with path.open("r", encoding="utf-8") as f:
        for index, line in enumerate(f):
            if not line.strip():
                continue
            data = json.loads(line)
            claimed_hash = data.pop("hash")
            if data["prev_hash"] != prev_hash:
                return False, index
            if _record_hash(data) != claimed_hash:
                return False, index
            prev_hash = claimed_hash

    return True, None
```

- [ ] **Step 6: Modify `core/config/defaults.yaml`** — add an `audit:` section

```yaml
audit:
  log_path: .promptwise/audit.jsonl
```

- [ ] **Step 7: Modify `core/diagnostics/checks.py`** — replace the `audit.chain` stub with a real check

Read the current file first. Remove `_not_yet_implemented("audit.chain", "Phase 3")` from the `run_diagnostics()` list and add a real `_check_audit_chain`:

```python
def _check_audit_chain(config: dict | None = None) -> CheckResult:
    from core.audit.log import verify_chain

    config = config if config is not None else resolve_config_auto()
    ok, broken_at = verify_chain(config)
    if ok:
        return CheckResult(name="audit.chain", status="PASS", message="hash chain unbroken")
    return CheckResult(
        name="audit.chain",
        status="FAIL",
        message=f"hash chain broken at record index {broken_at} — audit log may have been tampered with",
    )
```

Add `_check_audit_chain(config)` to `run_diagnostics()`'s returned list in place of the old `_not_yet_implemented("audit.chain", "Phase 3")` line, keeping the same list position.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest core/tests/audit/test_log.py core/tests/diagnostics/test_checks.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Run the full suite**

Run: `pytest -v`
Expected: PASS — note `core/tests/diagnostics/test_checks.py`'s existing test that asserts the 8 check names' statuses (from Phase 1) will need `audit.chain` to no longer be in the "always WARN" stubbed set; if that test breaks, update its expectation to match the real check (PASS on a clean/missing log), don't weaken the new check to make an old assertion pass.

- [ ] **Step 10: Commit**

```bash
git add core/audit/ core/config/defaults.yaml core/diagnostics/checks.py core/tests/audit/ core/tests/diagnostics/test_checks.py
git commit -m "feat: hash-chained audit log, real audit.chain doctor check"
```

---

### Task 2: Policy engine — `check_policy`

**Files:**
- Create: `core/policy/__init__.py`
- Create: `core/policy/models.py`
- Create: `core/policy/engine.py`
- Create: `policies/default.yaml`
- Modify: `core/diagnostics/checks.py` (make `policy.load` real, was stubbed WARN)
- Test: `core/tests/policy/__init__.py`
- Test: `core/tests/policy/test_engine.py`
- Test: `core/tests/diagnostics/test_checks.py` (append)

**Interfaces:**
- Consumes: `resolve_config_auto`, `resolve_path` (Phase 1); `record_audit` (Task 1, for logging decisions — this task's tests call `check_policy` directly without auditing; Task 4's `fs_write` is what wires the audit call).
- Produces: `PolicyRule(BaseModel)` (action: str — a glob-style pattern like `fs.write.*`; effect: Literal["allow","deny"]), `PolicyDecision(BaseModel)` (allowed: bool, reason: str, matched_rule: str | None), `load_policy(config: dict) -> list[PolicyRule]` (reads `policies/` dir, merges via simple concatenation — later files win on first-match order, `extends` inheritance is a v1.1 concern, not built here), `check_policy(action: str, config: dict | None = None) -> PolicyDecision`. Task 4's `fs_write` and Task 5's tool registry both call `check_policy`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/policy/__init__.py
```

```python
# core/tests/policy/test_engine.py
from core.policy.engine import check_policy, load_policy


def _config(tmp_path, rules_yaml: str):
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "test.yaml").write_text(rules_yaml)
    return {"paths": {"policies_dir": str(policies_dir)}, "policy": {"default_effect": "deny"}}


def test_load_policy_reads_rules_from_the_configured_dir(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.*\n    effect: allow\n")
    rules = load_policy(config)
    assert len(rules) == 1
    assert rules[0].action == "fs.write.*"
    assert rules[0].effect == "allow"


def test_check_policy_allows_a_matching_allow_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.*\n    effect: allow\n")
    decision = check_policy("fs.write.config", config=config)
    assert decision.allowed is True
    assert decision.matched_rule == "fs.write.*"


def test_check_policy_denies_a_matching_deny_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.write.secrets/*\n    effect: deny\n")
    decision = check_policy("fs.write.secrets/apikey", config=config)
    assert decision.allowed is False


def test_check_policy_defaults_to_deny_with_no_matching_rule(tmp_path):
    config = _config(tmp_path, "rules:\n  - action: fs.read.*\n    effect: allow\n")
    decision = check_policy("shell.exec.rm", config=config)
    assert decision.allowed is False
    assert decision.matched_rule is None
    assert "default" in decision.reason.lower()


def test_check_policy_first_match_wins(tmp_path):
    config = _config(
        tmp_path,
        "rules:\n"
        "  - action: fs.write.*\n"
        "    effect: deny\n"
        "  - action: fs.write.*\n"
        "    effect: allow\n",
    )
    decision = check_policy("fs.write.anything", config=config)
    assert decision.allowed is False  # first matching rule (deny) wins


def test_check_policy_default_effect_can_be_configured_to_allow(tmp_path):
    config = _config(tmp_path, "rules: []\n")
    config["policy"]["default_effect"] = "allow"
    decision = check_policy("anything.at.all", config=config)
    assert decision.allowed is True


def test_missing_policies_dir_falls_back_to_default_deny_without_crashing(tmp_path):
    config = {"paths": {"policies_dir": str(tmp_path / "does-not-exist")}, "policy": {"default_effect": "deny"}}
    decision = check_policy("fs.write.x", config=config)
    assert decision.allowed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/policy/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.policy'`

- [ ] **Step 3: Write `core/policy/__init__.py`** (empty package marker)

- [ ] **Step 4: Write `core/policy/models.py`**

```python
# core/policy/models.py
from typing import Literal

from pydantic import BaseModel


class PolicyRule(BaseModel):
    action: str
    effect: Literal["allow", "deny"]


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    matched_rule: str | None = None
```

- [ ] **Step 5: Write `core/policy/engine.py`**

```python
# core/policy/engine.py
"""check_policy — docs/ARCHITECTURE.md §2. Evaluate-and-return policy
engine over glob-pattern rules loaded from policies/ (repo-level) plus any
pack-contributed rules (packs are Phase 8, not wired here). First matching
rule wins; no match falls through to policy.default_effect (deny by
default, per CLAUDE.md's security posture).
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from core.config.resolve import resolve_config_auto
from core.policy.models import PolicyDecision, PolicyRule


def _policies_dir(config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("policies_dir", "policies")
    return Path(rel)


def load_policy(config: dict[str, Any] | None = None) -> list[PolicyRule]:
    config = config if config is not None else resolve_config_auto()
    directory = _policies_dir(config)
    if not directory.exists():
        return []

    rules: list[PolicyRule] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for raw_rule in data.get("rules", []):
            rules.append(PolicyRule(**raw_rule))
    return rules


def check_policy(action: str, config: dict[str, Any] | None = None) -> PolicyDecision:
    config = config if config is not None else resolve_config_auto()
    rules = load_policy(config)

    for rule in rules:
        if fnmatch.fnmatch(action, rule.action):
            allowed = rule.effect == "allow"
            return PolicyDecision(
                allowed=allowed,
                reason=f"matched rule '{rule.action}' -> {rule.effect}",
                matched_rule=rule.action,
            )

    default_effect = config.get("policy", {}).get("default_effect", "deny")
    allowed = default_effect == "allow"
    return PolicyDecision(
        allowed=allowed,
        reason=f"no matching rule, default_effect={default_effect}",
        matched_rule=None,
    )
```

- [ ] **Step 6: Write `policies/default.yaml`** — this repo's own shipped default policy (empty rule set, relies on default-deny; a real deployment adds rules here)

```yaml
# policies/default.yaml — docs/ARCHITECTURE.md §2. Empty by default: every
# action is denied unless a rule here (or a project-level policies file)
# explicitly allows it. This is intentional — see policy.default_effect
# in core/config/defaults.yaml.
rules: []
```

Also add `policies_dir: policies` to `core/config/defaults.yaml`'s `paths:` section (it already has `packs_installed`/`model_catalog` there from Phases 1-2 — add this as a third key, don't touch the other two).

- [ ] **Step 7: Modify `core/diagnostics/checks.py`** — replace the `policy.load` stub with a real check

```python
def _check_policy_load(config: dict | None = None) -> CheckResult:
    from core.policy.engine import load_policy

    config = config if config is not None else resolve_config_auto()
    try:
        rules = load_policy(config)
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad policy file
        return CheckResult(name="policy.load", status="FAIL", message=f"policy failed to load: {exc}")
    return CheckResult(name="policy.load", status="PASS", message=f"{len(rules)} rule(s) loaded")
```

Remove `_not_yet_implemented("policy.load", "Phase 3")` from `run_diagnostics()`'s list, add `_check_policy_load(config)` in the same position.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest core/tests/policy/test_engine.py core/tests/diagnostics/test_checks.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `pytest -v`
Expected: PASS (adjust any test that hardcoded the old "always WARN" stub list, same caveat as Task 1 Step 9)

- [ ] **Step 10: Commit**

```bash
git add core/policy/__init__.py core/policy/models.py core/policy/engine.py policies/default.yaml core/config/defaults.yaml core/diagnostics/checks.py core/tests/policy/ core/tests/diagnostics/test_checks.py
git commit -m "feat: check_policy engine with default-deny, real policy.load doctor check"
```

---

### Task 3: JIT permission grants

**Files:**
- Create: `core/policy/jit.py`
- Test: `core/tests/policy/test_jit.py`

**Interfaces:**
- Consumes: `resolve_path` (Phase 1).
- Produces: `JitGrant(BaseModel)` (scope: str, granted_at: str, expires_at: str), `grant_jit_permission(config: dict, scope: str, ttl_seconds: int) -> JitGrant`, `check_jit_grant(config: dict, scope: str) -> bool` (True only if an unexpired grant exists for that exact scope — expired grants are treated as absent, not specially flagged). A later phase's `fs_write`/`shell_exec` callers can consult this before falling back to `check_policy`; this phase's own `fs_write` (Task 4) does not consume JIT grants — the ROADMAP acceptance criterion is "JIT grant expires and is denied after TTL," which this task's own tests prove directly.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/policy/test_jit.py
from core.policy.jit import check_jit_grant, grant_jit_permission


def _config(tmp_path):
    return {"policy": {"jit_grants_path": str(tmp_path / "jit_grants.json")}}


def test_grant_jit_permission_returns_a_grant_with_expiry(tmp_path):
    config = _config(tmp_path)
    grant = grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    assert grant.scope == "shell.exec.git"
    assert grant.expires_at > grant.granted_at


def test_check_jit_grant_true_for_an_unexpired_grant(tmp_path):
    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    assert check_jit_grant(config, "shell.exec.git") is True


def test_check_jit_grant_false_for_an_unknown_scope(tmp_path):
    config = _config(tmp_path)
    assert check_jit_grant(config, "shell.exec.rm") is False


def test_check_jit_grant_false_after_ttl_expires(tmp_path, monkeypatch):
    import core.policy.jit as jit_module

    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=1)

    real_now = jit_module._now

    def _future_now():
        from datetime import timedelta

        return real_now() + timedelta(seconds=10)

    monkeypatch.setattr(jit_module, "_now", _future_now)
    assert check_jit_grant(config, "shell.exec.git") is False


def test_multiple_grants_for_different_scopes_are_independent(tmp_path):
    config = _config(tmp_path)
    grant_jit_permission(config, scope="shell.exec.git", ttl_seconds=60)
    grant_jit_permission(config, scope="fs.write.tmp", ttl_seconds=60)
    assert check_jit_grant(config, "shell.exec.git") is True
    assert check_jit_grant(config, "fs.write.tmp") is True
    assert check_jit_grant(config, "shell.exec.rm") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/policy/test_jit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.policy.jit'` (or `ImportError` for the not-yet-existing names)

- [ ] **Step 3: Write `core/policy/jit.py`**

```python
# core/policy/jit.py
"""JIT (just-in-time) permission grants — docs/ARCHITECTURE.md §2's
grant_jit_permission concept. Time-boxed, scope-keyed grants persisted to
a JSON file (same tier of durability as Phase 2's failure ledger) —
expired grants are treated as absent, never specially flagged, so a
caller checking `check_jit_grant` gets a plain bool.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config.resolve import resolve_path


class JitGrant(BaseModel):
    scope: str
    granted_at: str
    expires_at: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _grants_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "policy.jit_grants_path", ".promptwise/jit_grants.json")


def _load_grants(config: dict[str, Any]) -> dict[str, JitGrant]:
    path = _grants_path(config)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return {scope: JitGrant(**value) for scope, value in raw.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_grants(config: dict[str, Any], grants: dict[str, JitGrant]) -> None:
    path = _grants_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump({scope: grant.model_dump() for scope, grant in grants.items()}, f, indent=2)
    tmp_path.replace(path)


def grant_jit_permission(config: dict[str, Any], scope: str, ttl_seconds: int) -> JitGrant:
    now = _now()
    grant = JitGrant(
        scope=scope,
        granted_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
    )
    grants = _load_grants(config)
    grants[scope] = grant
    _save_grants(config, grants)
    return grant


def check_jit_grant(config: dict[str, Any], scope: str) -> bool:
    grants = _load_grants(config)
    grant = grants.get(scope)
    if grant is None:
        return False
    return datetime.fromisoformat(grant.expires_at) > _now()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/policy/test_jit.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/policy/jit.py core/tests/policy/test_jit.py
git commit -m "feat: JIT permission grants with TTL expiry"
```

---

### Task 4: Governed filesystem action + undo buffer

**Files:**
- Create: `core/actions/__init__.py`
- Create: `core/actions/models.py`
- Create: `core/actions/fs.py`
- Test: `core/tests/actions/__init__.py`
- Test: `core/tests/actions/test_fs.py`

**Interfaces:**
- Consumes: `check_policy` (Task 2), `record_audit` (Task 1).
- Produces: `FsWriteResult(BaseModel)` (path: str, allowed: bool, written: bool, reason: str), `UndoEntry(BaseModel)` (path: str, previous_content: str | None, timestamp: str — `None` means the file didn't exist before this write, so undo means delete), `fs_write(config: dict, path: Path, content: str) -> FsWriteResult` (checks `check_policy("fs.write." + path-derived-scope)`, and only if allowed: records the current content (or lack thereof) to the undo buffer, writes the file, records an audit entry — in that order; a denial is also audited), `undo_last(config: dict) -> UndoEntry | None` (reverts the most recent undo-buffer entry, returns it, or `None` if the buffer is empty).

- [ ] **Step 1: Write the failing test**

```python
# core/tests/actions/__init__.py
```

```python
# core/tests/actions/test_fs.py
from pathlib import Path

from core.actions.fs import fs_write, undo_last
from core.audit.log import verify_chain


def _config(tmp_path, allow: bool = True):
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    effect = "allow" if allow else "deny"
    (policies_dir / "test.yaml").write_text(f"rules:\n  - action: fs.write.*\n    effect: {effect}\n")
    return {
        "paths": {"policies_dir": str(policies_dir)},
        "policy": {"default_effect": "deny"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "actions": {"undo_buffer_path": str(tmp_path / "undo_buffer.json"), "undo_buffer_max": 50},
    }


def test_fs_write_allowed_writes_the_file(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "workdir" / "hello.txt"
    result = fs_write(config, target, "hello world")
    assert result.allowed is True
    assert result.written is True
    assert target.read_text() == "hello world"


def test_fs_write_denied_does_not_touch_the_file(tmp_path):
    config = _config(tmp_path, allow=False)
    target = tmp_path / "workdir" / "hello.txt"
    result = fs_write(config, target, "hello world")
    assert result.allowed is False
    assert result.written is False
    assert not target.exists()


def test_fs_write_records_an_audit_entry_either_way(tmp_path):
    config = _config(tmp_path, allow=True)
    fs_write(config, tmp_path / "a.txt", "x")
    config_deny = _config(tmp_path, allow=False)
    config_deny["audit"]["log_path"] = config["audit"]["log_path"]  # same log
    fs_write(config_deny, tmp_path / "b.txt", "y")
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_undo_last_restores_previous_content(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "existing.txt"
    target.write_text("original")
    fs_write(config, target, "overwritten")
    assert target.read_text() == "overwritten"
    entry = undo_last(config)
    assert entry is not None
    assert target.read_text() == "original"


def test_undo_last_deletes_a_file_that_did_not_exist_before(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "new_file.txt"
    fs_write(config, target, "brand new")
    assert target.exists()
    undo_last(config)
    assert not target.exists()


def test_undo_last_on_empty_buffer_returns_none(tmp_path):
    config = _config(tmp_path, allow=True)
    assert undo_last(config) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/actions/test_fs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.actions'`

- [ ] **Step 3: Write `core/actions/__init__.py`** (empty package marker)

- [ ] **Step 4: Write `core/actions/models.py`**

```python
# core/actions/models.py
from pydantic import BaseModel


class FsWriteResult(BaseModel):
    path: str
    allowed: bool
    written: bool
    reason: str


class UndoEntry(BaseModel):
    path: str
    previous_content: str | None
    timestamp: str
```

- [ ] **Step 5: Write `core/actions/fs.py`**

```python
# core/actions/fs.py
"""fs_write — the one governed filesystem action this phase ships.
docs/ARCHITECTURE.md §2's Action layer: policy-gated, audited, and
undo-buffered, in that order, on every call. This is the enforcement
point core/policy/engine.py's check_policy never had on its own —
check_policy only evaluates and returns a verdict; fs_write is what
actually honors it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.actions.models import FsWriteResult, UndoEntry
from core.audit.log import record_audit
from core.config.resolve import resolve_path
from core.policy.engine import check_policy


def _undo_buffer_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "actions.undo_buffer_path", ".promptwise/undo_buffer.json")


def _load_undo_buffer(config: dict[str, Any]) -> list[UndoEntry]:
    path = _undo_buffer_path(config)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return [UndoEntry(**item) for item in raw]
    except (json.JSONDecodeError, ValueError):
        return []


def _save_undo_buffer(config: dict[str, Any], buffer: list[UndoEntry]) -> None:
    path = _undo_buffer_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    max_size = config.get("actions", {}).get("undo_buffer_max", 50)
    trimmed = buffer[-max_size:]
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump([entry.model_dump() for entry in trimmed], f, indent=2)
    tmp_path.replace(path)


def fs_write(config: dict[str, Any], path: Path, content: str) -> FsWriteResult:
    path = Path(path)
    scope = f"fs.write.{path.name}"
    decision = check_policy(scope, config=config)

    if not decision.allowed:
        record_audit(config, actor="fs_write", action=scope, target=str(path), result="deny", detail={"reason": decision.reason})
        return FsWriteResult(path=str(path), allowed=False, written=False, reason=decision.reason)

    previous_content = path.read_text(encoding="utf-8") if path.exists() else None
    buffer = _load_undo_buffer(config)
    buffer.append(
        UndoEntry(path=str(path), previous_content=previous_content, timestamp=datetime.now(timezone.utc).isoformat())
    )
    _save_undo_buffer(config, buffer)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    record_audit(config, actor="fs_write", action=scope, target=str(path), result="allow")
    return FsWriteResult(path=str(path), allowed=True, written=True, reason=decision.reason)


def undo_last(config: dict[str, Any]) -> UndoEntry | None:
    buffer = _load_undo_buffer(config)
    if not buffer:
        return None

    entry = buffer.pop()
    _save_undo_buffer(config, buffer)

    target = Path(entry.path)
    if entry.previous_content is None:
        if target.exists():
            target.unlink()
    else:
        target.write_text(entry.previous_content, encoding="utf-8")

    return entry
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest core/tests/actions/test_fs.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/actions/ core/tests/actions/
git commit -m "feat: governed fs_write action with policy gate, audit trail, undo buffer"
```

---

### Task 5: MCP tool allowlist + kill switch

**Files:**
- Create: `core/policy/tool_registry.py`
- Modify: `gateway/mcp_server.py`
- Modify: `core/config/defaults.yaml`
- Test: `core/tests/policy/test_tool_registry.py`
- Test: `gateway/tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `resolve_path` (Phase 1).
- Produces: `ToolRegistryEntry(BaseModel)` (name: str, version: str, enabled: bool), `load_tool_registry(config: dict) -> dict[str, ToolRegistryEntry]`, `is_tool_allowed(config: dict, name: str) -> bool` (False if the tool isn't in the registry at all, or is present but `enabled: false` — the kill switch). The gateway's MCP server checks this before dispatching any tool call.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/policy/test_tool_registry.py
from core.policy.tool_registry import is_tool_allowed, load_tool_registry


def _config(tmp_path, registry_yaml: str):
    path = tmp_path / "tool_registry.yaml"
    path.write_text(registry_yaml)
    return {"policy": {"tool_registry_path": str(path)}}


def test_load_tool_registry_reads_entries(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    registry = load_tool_registry(config)
    assert "verify_output" in registry
    assert registry["verify_output"].enabled is True


def test_is_tool_allowed_true_for_an_enabled_registered_tool(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    assert is_tool_allowed(config, "verify_output") is True


def test_is_tool_allowed_false_for_an_unregistered_tool(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n")
    assert is_tool_allowed(config, "some_unpinned_tool") is False


def test_is_tool_allowed_false_when_kill_switched(tmp_path):
    config = _config(tmp_path, "tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: false\n")
    assert is_tool_allowed(config, "verify_output") is False


def test_missing_registry_file_denies_everything_without_crashing(tmp_path):
    config = {"policy": {"tool_registry_path": str(tmp_path / "does-not-exist.yaml")}}
    assert is_tool_allowed(config, "verify_output") is False
```

```python
# gateway/tests/test_mcp_server.py — append
async def test_verify_output_tool_is_registered_in_the_tool_registry():
    """The tool registry (core/policy/tool_registry.py) and the MCP server's
    actually-registered tools must agree — verify_output must be in both."""
    import yaml
    from pathlib import Path

    registry_path = Path("tool_registry.yaml")
    with registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    assert "verify_output" in registry["tools"]
    assert registry["tools"]["verify_output"]["enabled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/policy/test_tool_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.policy.tool_registry'`

- [ ] **Step 3: Write `core/policy/tool_registry.py`**

```python
# core/policy/tool_registry.py
"""MCP tool allowlist with a kill switch — docs/ARCHITECTURE.md §2's tool
registry (closes the P2/P7 gap in the research doc's language). An
unregistered or explicitly-disabled tool is rejected before it ever
reaches core logic — this is the enforcement boundary gateway/CLAUDE.md
describes ("MCP tool registry enforcement happens here at the boundary").
Version-pinning by hash is a Phase 8 (pack ecosystem) concern; this phase
ships name+version+enabled, the minimum needed for a real kill switch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from core.config.resolve import resolve_path


class ToolRegistryEntry(BaseModel):
    version: str
    enabled: bool


def _registry_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "policy.tool_registry_path", "tool_registry.yaml")


def load_tool_registry(config: dict[str, Any]) -> dict[str, ToolRegistryEntry]:
    path = _registry_path(config)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tools = data.get("tools", {})
    return {name: ToolRegistryEntry(**fields) for name, fields in tools.items()}


def is_tool_allowed(config: dict[str, Any], name: str) -> bool:
    registry = load_tool_registry(config)
    entry = registry.get(name)
    if entry is None:
        return False
    return entry.enabled
```

- [ ] **Step 4: Create `tool_registry.yaml`** at the repo root — this project's own registry, listing the one tool that exists so far

```yaml
# tool_registry.yaml — MCP tool allowlist, docs/ARCHITECTURE.md §2.
# Every tool the in-process MCP server (gateway/mcp_server.py) exposes
# must be listed here with enabled: true, or it is rejected at the
# boundary before core logic ever runs. Flip enabled: false as a kill
# switch — no code change, no redeploy needed.
tools:
  verify_output:
    version: "0.1.0"
    enabled: true
```

Add `tool_registry_path: tool_registry.yaml` to `core/config/defaults.yaml`'s `policy:` section (alongside `default_effect`, already there since Phase 0).

- [ ] **Step 5: Modify `gateway/mcp_server.py`** — enforce the registry before dispatching

Read the current file first (it has one `@mcp_app.tool()`-decorated `verify_output` function). Wrap the tool body with a registry check at its top:

```python
@mcp_app.tool()
def verify_output(diff: str, spec: str = "", cwd: str = "", ledger_key: str = "") -> dict:
    """Run the verification gate (tests, lint, Semgrep, Gitleaks) against
    the current working tree and report whether the change is safe to
    consider done. Call this after making any code change, before
    declaring the task complete.

    Args:
        diff: A description or unified diff of what changed (for logging
            and the failure-retry ledger — this function does not apply
            the diff itself, it checks the working tree as it stands).
        spec: The requirement/spec this change is meant to satisfy.
        cwd: Working directory to run checks in. Defaults to the server's
            own cwd if empty.
        ledger_key: A stable identifier for this task, used to detect
            repeated identical failures across retries. Leave empty to
            skip retry-loop tracking.
    """
    from pathlib import Path

    from core.config.resolve import resolve_config_auto
    from core.policy.tool_registry import is_tool_allowed

    config = resolve_config_auto()
    if not is_tool_allowed(config, "verify_output"):
        return {"error": "tool 'verify_output' is not enabled in the tool registry (tool_registry.yaml) — rejected at the boundary"}

    result = _verify_output(
        diff=diff,
        spec=spec or None,
        cwd=Path(cwd) if cwd else None,
        ledger_key=ledger_key or None,
    )
    return result.model_dump()
```

This is the only function body changed in the file — everything else (`from mcp.server.fastmcp import FastMCP`, `mcp_app = FastMCP(...)`, the `if __name__ == "__main__"` block) stays exactly as it is.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest core/tests/policy/test_tool_registry.py gateway/tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/policy/tool_registry.py core/config/defaults.yaml tool_registry.yaml gateway/mcp_server.py core/tests/policy/test_tool_registry.py gateway/tests/test_mcp_server.py
git commit -m "feat: MCP tool allowlist with a kill switch, enforced at the gateway boundary"
```

---

### Task 6: Support bundle + redaction

**Files:**
- Create: `core/diagnostics/redact.py`
- Create: `core/diagnostics/support_bundle.py`
- Modify: `scripts/promptwise.py` (add `support-bundle` command)
- Test: `core/tests/diagnostics/test_redact.py`
- Test: `core/tests/diagnostics/test_support_bundle.py`
- Test: `scripts/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `run_diagnostics` (Phase 0-1), `resolve_config_auto`, `resolve_path` (Phase 1).
- Produces: `redact_secrets(text: str) -> str`, `generate_support_bundle(config: dict, out_path: Path) -> Path` (writes a zip, returns the path). `promptwise support-bundle [--out path.zip]` CLI command.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/diagnostics/test_redact.py
from core.diagnostics.redact import redact_secrets


def test_redacts_an_api_key_looking_string():
    text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdef1234567890ABCDEF1234567890"
    redacted = redact_secrets(text)
    assert "sk-ant-api03" not in redacted
    assert "REDACTED" in redacted


def test_redacts_a_generic_password_assignment():
    text = 'password: "hunter2superSecret"'
    redacted = redact_secrets(text)
    assert "hunter2superSecret" not in redacted


def test_leaves_ordinary_text_untouched():
    text = "this is a normal log line about a test passing"
    assert redact_secrets(text) == text


def test_redacts_a_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
    redacted = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
```

```python
# core/tests/diagnostics/test_support_bundle.py
import zipfile

from core.diagnostics.support_bundle import generate_support_bundle


def test_generate_support_bundle_creates_a_zip_with_expected_entries(tmp_path):
    config = {
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "paths": {"packs_installed": str(tmp_path / "packs" / "installed")},
    }
    out_path = tmp_path / "bundle.zip"
    result = generate_support_bundle(config, out_path)
    assert result == out_path
    assert out_path.exists()
    with zipfile.ZipFile(out_path) as z:
        names = z.namelist()
    assert "doctor_output.txt" in names
    assert "resolved_config.yaml" in names


def test_generate_support_bundle_redacts_secrets_from_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTWISE_TESTSECRET__VALUE", "sk-ant-api03-shouldnotappear1234567890")
    config = {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}
    out_path = tmp_path / "bundle.zip"
    generate_support_bundle(config, out_path)
    with zipfile.ZipFile(out_path) as z:
        content = z.read("resolved_config.yaml").decode("utf-8")
    assert "sk-ant-api03-shouldnotappear1234567890" not in content
```

```python
# scripts/tests/test_cli.py — append
def test_support_bundle_command_creates_a_zip(tmp_path):
    out_path = tmp_path / "bundle.zip"
    result = runner.invoke(app, ["support-bundle", "--out", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/diagnostics/test_redact.py core/tests/diagnostics/test_support_bundle.py scripts/tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.diagnostics.redact'`

- [ ] **Step 3: Write `core/diagnostics/redact.py`**

```python
# core/diagnostics/redact.py
"""Shared redaction utility — docs/MAINTENANCE.md §3: "one implementation,
not two." Used by the support bundle (this phase) and, later, any
dashboard log-viewing panel (Phase 6). Pattern-based, not exhaustive —
covers the common secret shapes (API keys, bearer tokens, password
assignments); redacted before write, never after, per the same section.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.]{20,}"),
    re.compile(r'(?i)(password|passwd|secret|api[_-]?key)\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
```

- [ ] **Step 4: Write `core/diagnostics/support_bundle.py`**

```python
# core/diagnostics/support_bundle.py
"""generate_support_bundle — docs/MAINTENANCE.md §3. Collects doctor
output, the resolved config (redacted), and the audit trail tail into one
shareable zip. Log collection (per-pack structured logs) is a no-op for
now — no pack system exists yet (Phase 8); the bundle collects what this
phase's subsystems actually produce.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import yaml

from core.diagnostics.checks import run_diagnostics
from core.diagnostics.redact import redact_secrets


def _doctor_output_text(config: dict[str, Any]) -> str:
    results = run_diagnostics(config)
    lines = [f"[{r.status}] {r.name} — {r.message}" for r in results]
    return "\n".join(lines)


def _resolved_config_text(config: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(config, sort_keys=True)
    return redact_secrets(dumped)


def _audit_tail_text(config: dict[str, Any], max_lines: int = 200) -> str:
    from core.config.resolve import resolve_path

    path = resolve_path(config, "audit.log_path", ".promptwise/audit.jsonl")
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = "".join(lines[-max_lines:])
    return redact_secrets(tail)


def generate_support_bundle(config: dict[str, Any], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doctor_output.txt", _doctor_output_text(config))
        z.writestr("resolved_config.yaml", _resolved_config_text(config))
        z.writestr("audit_tail.jsonl", _audit_tail_text(config))

    return out_path
```

- [ ] **Step 5: Modify `scripts/promptwise.py`** — add the `support-bundle` command

Read the current file first (it has `doctor` and `profile` commands via `import core.diagnostics.checks as diagnostics_checks`). Add:

```python
@app.command()
def support_bundle(out: Path = Path("support-bundle.zip")) -> None:
    """Generate a redacted support bundle for troubleshooting."""
    from core.config.resolve import resolve_config_auto
    from core.diagnostics.support_bundle import generate_support_bundle

    config = resolve_config_auto()
    result = generate_support_bundle(config, out)
    typer.echo(f"wrote {result}")
```

Note: Typer auto-converts `support_bundle` (the Python function name) to the `support-bundle` CLI command name (underscores become hyphens) — this matches the `--out` test invocation without any extra `name=` argument needed. Verify this is still true for whatever Typer version is installed; if not, add `@app.command(name="support-bundle")` explicitly.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_redact.py core/tests/diagnostics/test_support_bundle.py scripts/tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/diagnostics/redact.py core/diagnostics/support_bundle.py scripts/promptwise.py core/tests/diagnostics/test_redact.py core/tests/diagnostics/test_support_bundle.py scripts/tests/test_cli.py
git commit -m "feat: redacted support-bundle generator and CLI command"
```

---

### Task 7: Upgrade dry-run (minimal Alembic wiring)

**Files:**
- Create: `core/models/__init__.py`
- Create: `alembic.ini`
- Create: `core/migrations/env.py`
- Create: `core/migrations/script.py.mako`
- Create: `core/migrations/versions/0001_initial_schema_version.py`
- Create: `core/diagnostics/upgrade.py`
- Modify: `pyproject.toml` (add `sqlalchemy`, `alembic` dependencies)
- Modify: `scripts/promptwise.py` (add `upgrade --dry-run` command)
- Test: `core/tests/diagnostics/test_upgrade.py`
- Test: `scripts/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `resolve_config_auto`.
- Produces: `core.models.Base` (SQLAlchemy declarative base), a `schema_version` table, `upgrade_dry_run(config: dict) -> dict` (returns `{"pending_migrations": list[str], "current_revision": str | None, "target_revision": str}`). `promptwise upgrade --dry-run` CLI command prints this report.

This task is the smallest slice of Alembic that makes the ROADMAP acceptance criterion ("`promptwise upgrade --dry-run` reports correctly on a seeded migration") real: one model, one migration, a dry-run report — not a migration of every table this project might eventually need. Later phases add their own models/migrations as they need persistence; this task only proves the mechanism works.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/diagnostics/test_upgrade.py
import subprocess
import sys
from pathlib import Path

from core.diagnostics.upgrade import upgrade_dry_run


def test_upgrade_dry_run_reports_pending_migration_on_a_fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    config = {"database": {"url": f"sqlite:///{db_path}"}}
    report = upgrade_dry_run(config)
    assert report["current_revision"] is None
    assert len(report["pending_migrations"]) >= 1
    assert report["target_revision"] is not None


def test_upgrade_dry_run_reports_clean_after_a_real_upgrade(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    config = {"database": {"url": db_url}}

    # Run the real alembic upgrade against this temp DB (proves the
    # migration itself is valid, not just that dry-run detects it).
    env = {"PROMPTWISE_DATABASE_URL": db_url}
    import os

    full_env = {**os.environ, **env}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        env=full_env,
        capture_output=True,
        text=True,
        check=True,
    )

    report = upgrade_dry_run(config)
    assert report["current_revision"] == report["target_revision"]
    assert report["pending_migrations"] == []
```

```python
# scripts/tests/test_cli.py — append
def test_upgrade_dry_run_command_reports_without_crashing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["upgrade", "--dry-run"])
    assert result.exit_code == 0
    assert "revision" in result.stdout.lower() or "migration" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/diagnostics/test_upgrade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.models'` (or `alembic` not installed yet)

- [ ] **Step 3: Modify `pyproject.toml`** — add the two new dependencies

In `[project].dependencies`, add `"sqlalchemy>=2.0"` and `"alembic>=1.13"`.

Run: `pip install -e ".[dev]"` to install them.

- [ ] **Step 4: Write `core/models/__init__.py`**

```python
# core/models/__init__.py
"""SQLAlchemy models — docs/ARCHITECTURE.md, core/CLAUDE.md. SQLite in
dev, schema written Postgres-clean (no SQLite-only types) so a
DATABASE_URL swap needs zero model changes, per core/CLAUDE.md's
convention. This phase ships exactly one table (schema_version) — just
enough to make `promptwise upgrade --dry-run` real. Later phases add
their own models here as they need real persistence.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
```

- [ ] **Step 5: Write `alembic.ini`** (repo root)

```ini
[alembic]
script_location = core/migrations
sqlalchemy.url = sqlite:///./config/promptwise.db

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 6: Write `core/migrations/env.py`**

```python
# core/migrations/env.py
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Allow an env var to override the URL for tests, matching this project's
# config-layering convention (PROMPTWISE_ prefix, __ nesting) — used by
# this task's own test to point alembic at a temp SQLite file.
db_url_override = os.environ.get("PROMPTWISE_DATABASE_URL")
if db_url_override:
    config.set_main_option("sqlalchemy.url", db_url_override)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 7: Write `core/migrations/script.py.mako`** (Alembic's standard template — required boilerplate, do not modify)

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 8: Write `core/migrations/versions/0001_initial_schema_version.py`**

```python
# core/migrations/versions/0001_initial_schema_version.py
"""initial schema_version table

Revision ID: 0001
Revises:
Create Date: 2026-08-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=100), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schema_version")
```

- [ ] **Step 9: Create empty `core/migrations/versions/__init__.py`** if Alembic's version discovery needs it as a package (check whether Alembic requires this — recent versions typically don't need `versions/` to be an importable package, just a directory of migration scripts; if `alembic upgrade head` works without it in Step 11's manual check below, skip creating this file).

- [ ] **Step 10: Write `core/diagnostics/upgrade.py`**

```python
# core/diagnostics/upgrade.py
"""upgrade_dry_run — docs/MAINTENANCE.md §5. Reports pending Alembic
migrations without applying them. Config-key/pack-constraint deprecation
reporting (also described in §5) has nothing to report yet — no packs
exist (Phase 8) and no config key has been deprecated yet — so this
phase's report is migrations-only; later phases extend the returned dict,
they don't replace this function's shape.
"""
from __future__ import annotations

from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


def upgrade_dry_run(config: dict[str, Any]) -> dict[str, Any]:
    db_url = config.get("database", {}).get("url", "sqlite:///./config/promptwise.db")

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    script = ScriptDirectory.from_config(alembic_cfg)
    target_revision = script.get_current_head()

    engine = create_engine(db_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_revision = context.get_current_revision()

    if current_revision == target_revision:
        pending: list[str] = []
    else:
        pending = [rev.revision for rev in script.iterate_revisions(target_revision, current_revision)]
        pending.reverse()

    return {
        "current_revision": current_revision,
        "target_revision": target_revision,
        "pending_migrations": pending,
    }
```

- [ ] **Step 11: Manually verify the Alembic setup works before trusting the test** — run `alembic -c alembic.ini upgrade head` against a scratch SQLite file once by hand (e.g. `alembic.ini`'s default `sqlalchemy.url`) and confirm it creates `schema_version` with no errors. Fix any path/import issue in `core/migrations/env.py` before proceeding — this is exactly the kind of "brief hedges the exact library-integration shape" situation Phase 2's Task 7 (MCP SDK) had; verify against the real installed `alembic`, adjust if its API/config expectations differ from the code above.

- [ ] **Step 12: Modify `scripts/promptwise.py`** — add the `upgrade` command

```python
@app.command()
def upgrade(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Show pending migrations without applying them (only --dry-run is implemented in this phase)."""
    from core.config.resolve import resolve_config_auto
    from core.diagnostics.upgrade import upgrade_dry_run

    if not dry_run:
        typer.echo("only --dry-run is implemented in this phase — real upgrade lands with the first schema change that needs it")
        raise typer.Exit(code=1)

    config = resolve_config_auto()
    report = upgrade_dry_run(config)
    typer.echo(f"current revision: {report['current_revision'] or '(none)'}")
    typer.echo(f"target revision: {report['target_revision']}")
    if report["pending_migrations"]:
        typer.echo(f"pending migrations: {', '.join(report['pending_migrations'])}")
    else:
        typer.echo("up to date, no pending migrations")
```

- [ ] **Step 13: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_upgrade.py scripts/tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 14: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 15: Modify `.gitignore`** — add `config/*.db` and `*.db` so nobody accidentally commits a local SQLite file (mirrors the existing `config/hardware_profile.yaml` ignore pattern)

- [ ] **Step 16: Commit**

```bash
git add core/models/ alembic.ini core/migrations/ core/diagnostics/upgrade.py pyproject.toml scripts/promptwise.py .gitignore core/tests/diagnostics/test_upgrade.py scripts/tests/test_cli.py
git commit -m "feat: minimal Alembic wiring, promptwise upgrade --dry-run"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** all 6 ROADMAP Phase 3 acceptance criteria covered — Task 4's `fs_write` proves fs actions pass through `check_policy` (100% of the one fs action this phase ships — shell/systemd are explicitly out of scope, see below); Task 3 proves JIT grants expire and deny after TTL; Task 1 proves the audit chain is verifiable and tamper-detecting; Task 5 proves the tool allowlist rejects an unregistered tool; Task 6 proves the support bundle produces a redacted zip; Task 7 proves `upgrade --dry-run` reports correctly on a seeded migration.
- **Scope note, not a placeholder:** per the confirmed lean-MVP scope decision (2026-08-21, `agentic-os-scope-decision` memory) and the external research's own risk flag ("highest-consequence code, thinnest schedule" for shell/systemd), this plan deliberately ships only the filesystem action (`fs_write`) as Phase 3's governed action — `shell_exec`/systemd control are NOT built here. This narrows "100% of fs/shell actions... pass through check_policy" to the fs actions that actually exist after this phase; a future plan can add `shell_exec` behind the same `check_policy`/audit/undo pattern once it gets its own design pass, per the research's explicit recommendation not to share a rushed two-week slot between fs and shell.
- **Placeholder scan:** no TBD/TODO. Task 7's Step 11 (manual Alembic verification) and Task 5's tool-registry test both carry explicit "verify against the real installed library/values" instructions, matching Phase 2's established pattern for genuinely library-version-sensitive code — not a placeholder, a bounded uncertainty the plan already flagged.
- **Type consistency:** `PolicyDecision` (Task 2) is the single shape `check_policy`'s callers (Task 4's `fs_write`, and implicitly Task 5's tool-registry design, which uses a simpler boolean rather than reusing `PolicyDecision` — deliberate, since tool-registry checks are binary allow/deny-only with no rule-matching detail to report) — Task 4 and Task 2 agree on `PolicyDecision`'s exact fields. `AuditRecord` (Task 1) is the only shape written to the audit log, used identically by Task 4's `fs_write`.

## Next plan after this one

Phase 4 — Memory & code context (`docs/ROADMAP.md` row 5): hybrid BM25+vector retrieval (Qdrant, already running from Phase 0's compose bundle but never yet queried), tree-sitter repo index, Mem0-style fact/decision extraction, PII exclusion from cloud-bound context, context policy (compaction via local model — also still blocked on the LiteLLM/real-model-call wiring Phase 2 noted as deferred; scope that dependency explicitly when writing the Phase 4 plan). Write that plan only after Phase 3's acceptance criteria are green.
