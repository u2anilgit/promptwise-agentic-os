# Dashboard slice 6e: chat and first-run wizard — Design

Status: **proposed, awaiting user review.** Written during an autonomous session (2026-10-20) in which the user asked for work to continue without questions. Every decision below is a recommendation; nothing in this document has been implemented. Resolve the "Decisions for the user" section before a plan is written.

Inputs: `docs/superpowers/specs/2026-10-17-dashboard-design.md` (D1–D7, slicing table), `docs/ROADMAP.md` Phase 6 criterion, `gateway/app.py`, `gateway/api/v1.py`, `core/routing/router.py`, `core/memory/extract.py` (the only existing model call), `core/routing/usage.py`.

## Intent

Close the Phase 6 roadmap criterion: *a clean install reaches a first successful chat in under 10 minutes.* Chat is the first place the dashboard **writes** and the first place the gateway itself **calls a model**. Both are new risk, so this slice must be narrow.

## What exists today

- `route_request` picks a tier, provider and model id. It does **not** call a model.
- The only model call in core is `core/memory/extract.py`: plain HTTP to Ollama `/api/generate`, fail-soft.
- `/api/v1` is GET-only by test. The only POST routes (`/route`, `/verify`, `/cost-report`) are bearer-protected, outside `/api/v1`, and called by tools, not browsers.
- Usage is self-reported by agents (`record_usage`). The gateway never sees model traffic.
- Auth: one shared bearer credential held in `sessionStorage`; strict CSP; no cookies.

## Goals

1. A chat panel that sends a prompt, shows which tier/model `route_request` chose and why, streams the local model's reply, and records the usage itself (measured, not self-reported).
2. A first-run wizard that checks what a first chat needs (gateway up, credential works, Ollama reachable, a local model pulled) and tells the operator the exact command to fix each gap.
3. Default path is local and $0. A cloud tier is never called unless the operator opted in.

## Non-goals

- No conversation memory or history persistence in this slice (no writes to `core/memory/` from chat).
- No tool use, agents or file access from chat. Chat is text in, text out.
- No model pulling from the browser (the wizard prints the `ollama pull` command; it does not run it).
- No cloud provider integration. LiteLLM stays out (ARCHITECTURE.md "LiteLLM posture").
- No multi-user accounts.

## Anti-goals

- A browser-reachable endpoint that runs arbitrary work: chat must not become a proxy for shell, fs or MCP tools.
- A write route that skips `check_policy` or the audit log.
- Rendering model output as HTML/markdown (model output is untrusted, D4).
- Logging prompt or completion text into the audit log by default (privacy; size).

## Recommended design

### R1. A core verb owns the model call: `chat_complete`
New `core/chat/` module with `chat_complete(messages, tier_hint=None, config) -> Iterator[ChatChunk]`:
1. `route_request` decides the tier. If the tier `requires_cloud` and `engine.local_only` is true (default), refuse with a reason code.
2. `check_policy("model:invoke:<tier>")` must allow it. Default policy ships an allow rule for local tiers only.
3. Calls Ollama `/api/chat` with `stream: true` (same plain-HTTP, fail-soft style as `extract.py`); bounded by `chat.max_prompt_chars`, `chat.max_output_tokens`, `chat.timeout_seconds`.
4. On completion, records usage with `agent="dashboard-chat"` and token counts **from Ollama's response** (`prompt_eval_count`, `eval_count`), marked `measured=true` (new nullable column, migration 0005), so the Cost view can tell measured from self-reported.
5. Audits `chat_complete` with tier, model, token counts, latency, prompt/completion **sha256 and length only**. Text is not stored unless `chat.audit_text: true`.

The gateway route is a thin adapter, consistent with "every route calls a core verb".

### R2. Write surface: one POST route, CSRF-safe by construction
`POST /api/v1/chat` (the GET-only test is amended to allow exactly this route, by name).
- **CSRF:** the credential travels only in the `Authorization` header from `sessionStorage`; there are no cookies, so a cross-site form or image request cannot carry it. Additionally require `Content-Type: application/json` (forces a CORS preflight for cross-origin fetch) and reject requests whose `Origin` header is present and not the gateway's own origin. No CORS middleware is added.
- **Rate limit:** in-process token bucket per credential (`chat.rate_per_minute`, default 20) plus a concurrency cap of 2 streams, mirroring `MAX_STREAMS` in `/events`. Returns 429.
- **Body limits:** request size cap; message count cap.
- **Response:** SSE over `fetch` streaming (same client code path as `/events`): `event: route` (decision), `event: token` (text chunks), `event: done` (usage + latency) or `event: error` (reason code). Text chunks are rendered as plain text only.

### R3. Wizard: read-only checks, operator runs the fixes
`GET /api/v1/setup` returns ordered steps from a new core function built on `run_diagnostics` plus two new checks: `models.local_available` (Ollama `/api/tags` contains the catalog's local tier model) and `chat.policy` (a local tier is allowed by policy). Each step: `status`, plain-language `explanation` (Builder) and the exact `fix` command (for example `ollama pull <model>`, `promptwise dashboard token`). The UI shows a checklist and a "Try a first chat" button that unlocks when all required steps pass. The wizard writes nothing.

First-run detection: the dashboard opens the wizard when `/api/v1/setup` reports any required step failing; otherwise it opens the audit view as today. No server-side "first run" flag.

### R4. UI
- New `#/chat` route and nav link. Prompt box, send, stop (aborts the fetch), transcript kept in component state only (lost on reload, by design for this slice).
- Each reply shows a routing badge (tier, local/cloud, reason) and its measured cost. Builder mode explains the route in a sentence via `explain.ts`.
- Model output is rendered with the same escaped-text component as audit detail.

### R5. Timed acceptance run
Roadmap criterion verified by a recorded manual run on a clean machine (or a clean VM/container): `docker compose up` (or native install) → open dashboard → wizard → first chat, with timestamps in `docs/research/` and the result in `docs/ROADMAP.md`. Plus automated: a Playwright test against the e2e gateway with a **fake Ollama** (a tiny local HTTP stub started by `scripts/e2e_gateway.py`) covering wizard gaps, a streamed reply, stop, 429, and that hostile model output renders inert.

## Decisions for the user (blocking the plan)

1. **Measured vs self-reported usage.** Add a `measured` column (migration 0005) so chat usage is distinguishable? *Recommended: yes.*
2. **Audit text.** Store only hashes/lengths of prompts and replies by default, with an operator opt-in to store text? *Recommended: yes, hashes by default.*
3. **Cloud tiers in chat.** Leave cloud completely out of 6e (local only), deferring a provider interface to its own design? *Recommended: yes, local only.*
4. **Default policy.** Ship `model:invoke:local-*` as allowed in the default `policies/`? Without it, chat is denied out of the box and the wizard shows the fix. *Recommended: ship the allow rule for local tiers.*
5. **Transcript persistence.** None in 6e (component state only)? *Recommended: none; history becomes a separate slice with its own privacy review.*

## Risks

- **Ollama not installed / model missing** is the likeliest failure on a clean install, and it is outside the 10-minute budget's control (model download time depends on bandwidth). Mitigation: the wizard recommends the smallest catalog local model and states its download size; the timed run records download time separately.
- **First write route** widens the attack surface. Mitigations above (no cookies, Origin check, JSON-only, rate limit, policy gate, audit). Requires a dedicated security review of the slice before merge.
- **Streaming through the strict CSP**: `connect-src 'self'` already covers same-origin fetch streaming; no CSP change expected.
- **Usage double counting** if an agent also self-reports chat usage: avoided because only the dashboard uses `/api/v1/chat`, with a distinct agent name.

## Slicing inside 6e

1. `core/chat/` verb + policy action + usage `measured` column + audit (no HTTP).
2. `POST /api/v1/chat` SSE route with CSRF/rate-limit guards; GET-only test amended by name.
3. `GET /api/v1/setup` + new diagnostics checks.
4. UI: wizard + chat route; Playwright with fake Ollama.
5. Timed clean-install run, roadmap update.

Each part: failing test first, independent review, Critical/Important fixed before merge.
