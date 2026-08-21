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
