# Governed `shell_exec` verb — Plan

Date: 2026-10-20. Closes the goal-4 gap recorded in `docs/BACKLOG.md` (verify_output, acceptance checks and baseline runs shell out through `run_command` without `check_policy` or an audit record).

## Design

`core/actions/shell.py` (the Action layer, next to `fs_write`):

- `command_action(command, base) -> str` — moved from `core/spec/engine.py` unchanged: a bare program maps to `shell:run:<name>` (`.exe` stripped); anything with a path separator maps to its resolved absolute path, so a file merely named like an allowed program cannot ride on its rule.
- `shell_exec(tool_name, command, cwd, config, actor, enforce_policy, timeout, max_output_chars) -> ToolRunResult`:
  1. Blank command → skipped (`ran=False, passed=True`), no audit, same as today's "not configured".
  2. If `enforce_policy`, `check_policy(action)`; a denial is audited (`shell_exec`, result `deny`) and returned as `ran=False, passed=False, error_kind="policy_denied"` without running anything.
  3. A pre-run audit record (`shell_exec`, result `allow`, phase `start`) is written **before** the process starts; if it cannot be written the command does not run (`error_kind="audit_unavailable"`), mirroring the MCP boundary's fail-closed rule.
  4. Runs through the existing `run_command` (same parsing, timeouts, error kinds).
  5. A best-effort outcome record (phase `end`: passed, error_kind, duration, sha256 of the output) follows.
  The command text is recorded truncated to 500 characters; output is never stored, only its hash.

## Wiring

- `core/verify/runners.py`: `run_tests`, `run_lint`, `run_mutation` call `shell_exec` (actor `verify`). Policy enforcement there follows the new `verify.enforce_command_policy` (default **false**, because the default policy is deny-all and test runners are stack-specific: allow rules belong in packs/operator policy). Audit is always on. Flip the default once packs ship runner rules.
- `core/spec/engine.py`: baseline and acceptance runs call `shell_exec` (actor `spec_engine`). The engine keeps its explicit pre-check so a denial still yields per-requirement reasons before anything runs; `shell_exec` is called with `enforce_policy` equal to `spec.enforce_command_policy`, so the run itself is gated too.
- Reviewer command stays on its own runner (stdin payload, bounded output); recorded as a remaining gap.

## Tests (failing first)

- `core/tests/actions/test_shell.py`: denial does not run and is audited; allowed run audits start+end with output hash and no output text; unwritable audit log → not run; blank command → skipped, no audit; `command_action` mapping (moved tests keep passing).
- verify: a configured test command produces `shell_exec` audit records; with `verify.enforce_command_policy: true` and no allow rule, the gate reports the denial and does not pass.
- spec: an acceptance run produces a `shell_exec` record with actor `spec_engine`.
