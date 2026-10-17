# gateway/ — FastAPI Entrypoint

Scoped context. Read root `CLAUDE.md` and `docs/ARCHITECTURE.md` first.

## Responsibility

The only network-facing process. Three surfaces, one process:

1. **REST/WebSocket API** — backs the dashboard (chat, cost/routing badges, audit/policy viewer, diagnostics panel).
2. **MCP server** — exposes core verbs to any MCP-capable agent (Claude Code, Cursor, OpenCode, custom). Built on the official Python `mcp` SDK, hosted in-process (same Python interpreter as the FastAPI app) — calls core verbs directly, no cross-language hop. This is what `docs/ARCHITECTURE.md` §5 means by "one language across gateway, verify-gate, and MCP servers minimizes integration seams"; resolved 2026-08-21 (Phase 2 planning), replacing an earlier draft that named the TypeScript MCP SDK.
3. **OpenAI-compatible proxy** — thin pass-through to LiteLLM so any tool that speaks the OpenAI chat-completions shape gets routed through `route_request` transparently.

## Layout (target)

```
gateway/
  api/            REST routes — one file per resource (chat, audit, policy, packs, diagnostics)
  ws/             WebSocket handlers (live audit/cost feed)
  mcp/            MCP server adapter — verb-to-tool mapping, tool registry enforcement
  proxy/          OpenAI-compat endpoint → LiteLLM
  middleware/      auth, request logging, rate limiting
  healthcheck.py   backs `promptwise doctor`'s `services.gateway` check
```

## Conventions

- Every route calls a `core/` verb — no business logic in `gateway/`. If a route needs logic beyond request parsing/response shaping, that logic belongs in `core/`.
- MCP tool registry enforcement happens here at the boundary: an unpinned/unhashed tool call is rejected before it reaches `core.policy.check_policy`, not after.
- WebSocket audit/cost feed reads from `record_audit`'s append log, never a separate cache that can drift.
- `healthcheck.py` is what `compose/docker-compose.yml` points its `healthcheck:` directive at — keep it fast (<200ms), no deep checks (those live in `promptwise doctor`).

## HTTP auth and dashboard API (slice 6a)

Every HTTP route except `/healthz` requires `Authorization: Bearer <credential>` (`gateway/auth.py`). The credential is one operator-owned file (`gateway.token_path`, default `.promptwise/dashboard_token`, gitignored), generated on first use and re-read per request; replace the file to rotate, print it with `promptwise dashboard token`. Denials return a bare 401, are audited as `api_auth_denied` at most once per second, and never record the offered value. `/api/v1` (`gateway/api/v1.py`) is GET-only (a test enforces it): `/audit` (cursor/limit/filters, `tail=true`, always returns the hash-chain verdict), `/specs`, `/specs/{id}`, `/specs/{id}/history` (that spec's audit entries, exact target match, limit <= 200), `/policy`, `/usage` (self-reported usage report plus tier locality), `/diagnostics`, and `/events` (SSE of new audit records; `id:` is a byte cursor, `Last-Event-ID` resumes, the stream ends after `gateway.sse_max_seconds` so clients reconnect). Browsers' `EventSource` cannot send headers, so the dashboard consumes `/events` with `fetch` streaming. State paths come from the operator config, like the MCP boundary. Design: `docs/superpowers/specs/2026-10-17-dashboard-design.md`.

## MCP Server

Built on `mcp` SDK 2.x (`MCPServer`, protocol revision 2026-07-28; the legacy `initialize` flow still negotiates for older clients). Start standalone: `python -m gateway.mcp_server` (use the project `.venv`, see `docs/MAINTENANCE.md` 2b). Claude Code (and any other MCP-capable client) auto-discovers it via the repo-root `.mcp.json` once this repo is opened as a project — no manual registration needed. It exposes 13 tools (`gateway/mcp_server.py`), each a thin adapter over a core verb: `verify_output`, `query_code_index`, `record_memory`, `query_memory`, `run_ingestion_sweep`, `record_usage` (agent-reported tokens; cost fixed from the catalog tier and stored, see `docs/MAINTENANCE.md`), and the spec engine's `specify_feature`, `plan_feature`, `tasks_feature`, `complete_task`, `verify_feature`, `converge_feature`, `amend_check`. `orchestrate_tasks` is not exposed (it takes Python callables). List them with `promptwise mcp tools`.

### Governed boundary (`gateway/mcp_guard.py`)

Every tool runs through `run_governed`: (1) `tool_registry.yaml` entry must exist, be enabled and its `description_sha256` pin must match the live description + schema (re-pin with `promptwise pin-tools` after reviewing a change; `gateway/tests/test_mcp_registry_consistency.py` fails on a stale pin); (2) every `root`/`cwd` argument is resolved (symlinks and `..` included) and must lie inside `gateway.allowed_roots` (default: the gateway's cwd) — otherwise denied and audited as `mcp_root_denied`; (3) the call runs on the **operator config** — an allowlist model: the only project-supplied values honoured are `verify.test_command` / `verify.lint_command`, and only when that exact string is in the operator's `gateway.allowed_verify_commands` (otherwise ignored, so an agent cannot forge a grounded pass or run an arbitrary test command); every other key — endpoints (`memory.*_url`), limits, timeouts, policy, `engine.local_only`, `database.*` — is the operator's, and governance state (audit log, failure ledger, JIT grants, undo buffer, spec database) is pinned to the gateway's own directory, never the project's; (4) a pre-call audit record is written first — if it cannot be written the tool does not run — and a completion record after (a failed one is surfaced as `audit_warning`); denials at the registry/pin/root are audited too; (5) failures return `{"error": ...}`, never a transport error; (6) `verify_output`/`complete_task` test and lint output is returned wrapped as untrusted; `query_memory.limit` and `run_ingestion_sweep.session_texts` are bounded. `query_memory` returns each fact wrapped in `<untrusted source="memory">` with `risk_flags`.

**Operator config** = system defaults + the file named by `PROMPTWISE_OPERATOR_CONFIG` + process environment (`PROMPTWISE_*`). It deliberately excludes the working directory's org/project/local layers, because the gateway's cwd may be the project an agent is editing. Hardening: keep the operator file, `policies/`, `tool_registry.yaml` and the audit log outside any path the agent can write (point `policy.tool_registry_path`, `paths.policies_dir`, `audit.log_path` there in the operator file). In a plain single-repo setup (gateway cwd = the project) those files, including the spec database, are agent-writable and the protection is git review only; an agent with direct file access could also forge spec state. Allowing an interpreter in `policies/` (`shell:run:python`) allows arbitrary code run through it — prefer allowing specific test runners and pre-approving exact verify commands.
