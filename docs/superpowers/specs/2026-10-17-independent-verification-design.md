# Design: Independent verification — checks that must be able to fail

**Date:** 2026-10-17. **Status:** decisions made by the assistant under the user's standing instruction ("go ahead continuously as per the road map and plan"); user to review. Builds on `2026-10-16-spec-engine-v2-design.md` (frozen + grounded acceptance checks).
**Grounding:** `docs/research/2026-10-16-agent-landscape-gap-analysis.md` pain point 7 ("almost-right code verified by the agent's own tests"); ROADMAP Phase 2 addendum; the spec-engine-v2 review ("check quality is out of scope").

## Problem

v2 freezes acceptance checks before implementation and requires a grounded gate, so an agent can no longer *edit* a check or skip tests. It can still pass with a check that **cannot fail**: `python -c "pass"`, a script that `sys.exit(0)`s, a test with no assertions. "Frozen" and "grounded" prove the check ran and wasn't touched, not that it can detect a wrong implementation. The remaining gap is check *quality*.

## Goals / non-goals / anti-goals

- **Goal:** a task cannot reach `done` on the strength of a check that has never been seen to fail.
- **Goal:** let an operator add *independent* verification (mutation testing, a second reviewer) without core knowing any language or calling any LLM.
- **Non-goal:** core does not implement mutation testing, parse any tool's output, or call a model. It orchestrates operator-supplied commands (CLAUDE.md: "orchestrated, not reimplemented").
- **Anti-goal:** forcing ceremony on every tiny change. Everything beyond Ruling 1 is opt-in per operator config.

## Ruling 1 — Red before green (built in, on by default)

At freeze time (`tasks_feature`, and `amend_check`) every acceptance check is executed once, policy-gated and time-limited like at completion:
- `AcceptanceCheck.expect_baseline` is `"fail"` (default) or `"pass"`.
- `"fail"` (new behaviour): the check must **fail** now, before the work exists. A check that already passes is vacuous or already satisfied → `ValueError("... already passes before implementation; fix the check, or set expect_baseline='pass' if it guards behaviour that must keep working")`.
- `"pass"` (regression guard): must currently **pass**; a guard that already fails is broken → `ValueError`.
- The observed baseline (`failed`/`passed`) is stored on the frozen check and audited per requirement. `complete_task` rejects (`baseline_not_proven:Rn`) a check with no recorded baseline. A check that is `expect_baseline="pass"` is shown as such in status/audit — an explicit, reviewable choice, not silent.
- Cost if wrong: a legitimately-already-true requirement needs one explicit flag. Domain-agnostic: it only runs a configured command and reads its exit status.

## Ruling 2 — Mutation gate (opt-in, operator command)

`verify.mutation_command` (operator config; e.g. a mutation-testing tool wrapper). `verify_output` runs it after tests pass; **exit 0 = the tool's own score threshold met**. Non-zero or timeout blocks (`mutation testing failed`). It appears in `VerifyResult.results` as tool `mutation`. `spec.require_mutation: true` makes `complete_task` reject (`mutation_not_run`) unless it ran and passed. Core never parses scores; the tool owns its threshold.

## Ruling 3 — Independent reviewer hook (opt-in, operator command)

`verify.reviewer_command` (operator config) is invoked by `complete_task` with a JSON document on stdin: `{"spec_id", "task_id", "requirements": [{id,text}], "evidence", "checks": [{requirement_id, command, passed}]}` and must print `{"approved": bool, "reasons": [str]}` on stdout. Exit non-zero, timeout, malformed JSON, or `approved != true` → rejected (`reviewer_rejected` / `reviewer_failed`); fail closed. The command can call any other model, agent or a human; core calls no LLM. `spec.require_reviewer: true` rejects when no reviewer is configured (`reviewer_not_configured`). Reasons are length-bounded and returned to the agent as untrusted data at the MCP boundary.

## Ruling 4 — Visibility

`CompletionResult.independence = {"baseline_red": bool, "mutation": bool, "reviewer": bool}` and the audit entry for each accepted task record which independent layers backed it, so "done" is never an unqualified claim. `promptwise spec status` shows per-check baseline.

## Trust model

`mutation_command` and `reviewer_command` are execution surfaces: they are read **only from operator config** (the MCP effective config already ignores project values for every `verify.*` key except pre-approved `test_command`/`lint_command`). Baseline runs use the same `shell:run:<program>` policy gate as completion.

## Out of scope

Bundling any mutation tool or model client; semantic judgement of check quality beyond "can fail"; per-line mutation reporting.
