import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "./api/credential";
import { explainAction } from "./explain";
import { CostView } from "./features/cost/CostView";
import { ModeProvider } from "./mode";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
beforeEach(() => setCredential("tok"));

describe("explainAction is keyed on who wrote the entry", () => {
  it("describes spec-engine outcomes only for the spec engine", () => {
    expect(explainAction("complete_task", "allow", "spec_engine")).toMatch(/accepted/i);
    expect(explainAction("complete_task", "deny", "spec_engine")).toMatch(/rejected/i);
  });

  it("does not describe the MCP boundary's own bookkeeping rows as acceptances", () => {
    // run_governed writes complete_task/allow rows (actor mcp) even when the engine rejects the task
    expect(explainAction("complete_task", "allow", "mcp")).toBeNull();
    expect(explainAction("specify", "allow", "someone-else")).toBeNull();
  });

  it("does not claim an acceptance or rejection for an error outcome", () => {
    expect(explainAction("complete_task", "error", "spec_engine")).toBeNull();
  });

  it("keeps the boundary and auth sentences for their own actors", () => {
    expect(explainAction("mcp_root_denied", "deny", "mcp")).toMatch(/outside the allowed/i);
    expect(explainAction("api_auth_denied", "deny", "api")).toMatch(/wrong credential/i);
    expect(explainAction("api_auth_denied", "deny", "mcp")).toBeNull();
  });
});

describe("CostView figures", () => {
  const base = (over: Record<string, unknown> = {}) => ({
    report: {
      days: 7, events: 1, tasks: 1, tokens_in: 4, tokens_out: 0, total_cost_usd: 0.0000004, cost_per_task_usd: 0.0000004,
      by_tier: {}, by_agent: { "(other)": { events: 5, tokens_in: 1, tokens_out: 1, cost_usd: 0.01 } }, recent: [], ...over,
    },
    tiers: [], self_reported: true,
  });
  const renderCost = () =>
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ModeProvider><CostView onSignedOut={() => {}} /></ModeProvider></QueryClientProvider>);

  it("labels the tile honestly: tasks are the ones agents named, not accepted completions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(base())));
    renderCost();
    expect(await screen.findByText(/cost per referenced task/i)).toBeInTheDocument();
    expect(screen.queryByText(/cost per completed task/i)).not.toBeInTheDocument();
  });

  it("shows sub-cent costs with significant digits rather than $0.0000", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(base())));
    renderCost();
    expect((await screen.findAllByText(/\$4\.0e-7|\$0\.0000004/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("$0.0000")).not.toBeInTheDocument();
  });

  it("never prints exponent notation for large values or NaN", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(base({ total_cost_usd: 1e21, cost_per_task_usd: null }))));
    renderCost();
    await screen.findByText(/cost per referenced task/i);
    expect(document.body.textContent).not.toMatch(/e\+21|NaN|Infinity/);
  });
});
