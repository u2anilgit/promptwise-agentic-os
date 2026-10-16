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

## MCP Server

Start standalone: `python -m gateway.mcp_server`. Claude Code (and any other MCP-capable client) auto-discovers it via the repo-root `.mcp.json` once this repo is opened as a project — no manual registration needed. It exposes 12 tools (`gateway/mcp_server.py`), each a thin adapter over a core verb: `verify_output`, `query_code_index`, `record_memory`, `query_memory`, `run_ingestion_sweep`, and the spec engine's `specify_feature`, `plan_feature`, `tasks_feature`, `complete_task`, `verify_feature`, `converge_feature`, `amend_check`. `orchestrate_tasks` is not exposed (it takes Python callables). List them with `promptwise mcp tools`.

### Governed boundary (`gateway/mcp_guard.py`)

Every tool runs through `run_governed`: (1) `tool_registry.yaml` entry must exist, be enabled and its `description_sha256` pin must match the live description + schema (re-pin with `promptwise pin-tools` after reviewing a change; `gateway/tests/test_mcp_registry_consistency.py` fails on a stale pin); (2) every `root`/`cwd` argument is resolved (symlinks and `..` included) and must lie inside `gateway.allowed_roots` (default: the gateway's cwd) — otherwise denied and audited as `mcp_root_denied`; (3) the call runs with the project's config **except** governance keys (`audit`, `policy`, `security`, `gateway`, `paths.policies_dir`, `spec.enforce_command_policy`, `spec.allow_ungrounded`, `spec.allow_fileless_checks`, `spec.trivial_max_requirements`) which are forced from the **operator config**; (4) each call is audited (`actor=mcp`); (5) failures return `{"error": ...}`, never a transport error. `query_memory` returns each fact wrapped in `<untrusted source="memory">` with `risk_flags`.

**Operator config** = system defaults + the file named by `PROMPTWISE_OPERATOR_CONFIG` + process environment (`PROMPTWISE_*`). It deliberately excludes the working directory's org/project/local layers, because the gateway's cwd may be the project an agent is editing. Hardening: keep the operator file, `policies/`, `tool_registry.yaml` and the audit log outside any path the agent can write (point `policy.tool_registry_path`, `paths.policies_dir`, `audit.log_path` there in the operator file). In a plain single-repo setup those files are agent-writable and the protection is git review only.
