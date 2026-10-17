import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "./api/credential";
import { explainAction, explainReason } from "./explain";
import { CostView } from "./features/cost/CostView";
import { ModeProvider, ModeToggle, useMode } from "./mode";
import { AuditView } from "./features/audit/AuditView";
import { SpecDetail } from "./features/specs/SpecDetail";
import type { StreamOptions } from "./api/sse";

vi.mock("./api/sse", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api/sse")>();
  return { ...original, streamAudit: vi.fn(async (o: StreamOptions) => new Promise<void>((r) => o.signal.addEventListener("abort", () => r()))) };
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const qc = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
beforeEach(() => setCredential("tok"));

describe("explain lookup", () => {
  it.each([
    ["acceptance_check_failed:R1", /requirement R1.*did not pass/i],
    ["baseline_not_proven:R2", /R2.*never seen failing/i],
    ["checks_failing:R3", /R3.*not satisfied/i],
    ["acceptance_check_modified:tests/a.py", /tests\/a\.py.*changed after/i],
  ])("explains %s", (code, expected) => expect(explainReason(code)).toMatch(expected));

  it("falls back to the raw code instead of inventing prose", () => {
    expect(explainReason("something_new:x")).toBe("something_new:x");
    expect(explainReason("")).toBe("");
  });

  it("explains known audit actions by outcome and returns null for unknown ones", () => {
    expect(explainAction("complete_task", "allow")).toMatch(/accepted/i);
    expect(explainAction("complete_task", "deny")).toMatch(/rejected/i);
    expect(explainAction("mcp_root_denied", "deny")).toMatch(/outside the allowed/i);
    expect(explainAction("api_auth_denied", "deny")).toMatch(/wrong credential/i);
    expect(explainAction("never_heard_of_it", "allow")).toBeNull();
  });
});

describe("mode toggle", () => {
  function Probe() {
    const { mode } = useMode();
    return <span data-testid="mode">{mode}</span>;
  }

  it("defaults to pro, switches, and remembers per tab in sessionStorage only", async () => {
    render(<ModeProvider><ModeToggle /><Probe /></ModeProvider>);
    expect(screen.getByTestId("mode")).toHaveTextContent("pro");
    await userEvent.click(screen.getByRole("button", { name: /builder/i }));
    expect(screen.getByTestId("mode")).toHaveTextContent("builder");
    expect(sessionStorage.getItem("promptwise.mode")).toBe("builder");
    expect(localStorage.length).toBe(0);
  });

  it("ignores a corrupt stored value", () => {
    sessionStorage.setItem("promptwise.mode", "<script>");
    render(<ModeProvider><Probe /></ModeProvider>);
    expect(screen.getByTestId("mode")).toHaveTextContent("pro");
  });
});

describe("Builder mode changes disclosure, never the warnings", () => {
  const record = (over: Record<string, unknown> = {}) => ({
    id: "a", timestamp: "t", actor: "mcp", action: "mcp_root_denied", target: "/etc", result: "deny",
    detail: { value: "/etc" }, prev_hash: "p", hash: "h", ...over,
  });

  it("audit: shows a plain sentence and hides raw detail, but keeps the broken-chain alert", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ records: [record()], next_cursor: 1, chain: { ok: false, broken_at: 7 } })));
    sessionStorage.setItem("promptwise.mode", "builder");
    render(<ModeProvider><AuditView chainPollMs={100000} /></ModeProvider>);
    expect(await screen.findByText(/outside the allowed/i)).toBeInTheDocument();
    expect(screen.queryByText("detail")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/broken at record 7/i);
  });

  it("audit: pro mode keeps the raw action and detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ records: [record()], next_cursor: 1, chain: { ok: true, broken_at: null } })));
    render(<ModeProvider><AuditView chainPollMs={100000} /></ModeProvider>);
    expect(await screen.findByText("mcp_root_denied")).toBeInTheDocument();
    expect(screen.getByText("detail")).toBeInTheDocument();
  });

  it("spec detail: explains a denial reason in words and still flags an unproven baseline", async () => {
    const spec = {
      spec_id: "s1", request: "r", complexity: "standard", stage: "implementing", requirements: [{ id: "R1", text: "t" }],
      tasks: [], checks: [{ requirement_id: "R1", command: "x", files: [], expect_baseline: "fail", baseline: "unverified", file_hashes: {} }],
    };
    const history = { records: [{ ...record({ id: "h", actor: "spec_engine", action: "complete_task", target: "s1", detail: { task_id: "t1", reasons: ["acceptance_check_failed:R1"] } }) }], next_cursor: 1, truncated: false };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (u: string) => (String(u).includes("/history") ? json(history) : json(spec))));
    sessionStorage.setItem("promptwise.mode", "builder");
    render(<QueryClientProvider client={qc()}><ModeProvider><SpecDetail specId="s1" onBack={() => {}} onSignedOut={() => {}} /></ModeProvider></QueryClientProvider>);
    expect(await screen.findByText(/requirement R1.*did not pass/i)).toBeInTheDocument();
    expect(screen.getByText(/baseline not proven/i)).toBeInTheDocument();
  });
});

describe("CostView", () => {
  const bucket = (events: number, cost: number) => ({ events, tokens_in: 1000 * events, tokens_out: 500 * events, cost_usd: cost });
  const body = (over: Record<string, unknown> = {}) => ({
    report: {
      days: 7, events: 3, tasks: 2, tokens_in: 3000, tokens_out: 1500, total_cost_usd: 0.04, cost_per_task_usd: 0.02,
      by_tier: { "local-small": bucket(1, 0), "cloud-premium": bucket(2, 0.04) },
      by_agent: { claude: bucket(3, 0.04) },
      recent: [{ id: 1, ts: 1, tier: "cloud-premium", tokens_in: 10, tokens_out: 5, cost_usd: 0.01, agent: "<b>evil</b>", task_ref: "T-1", spec_id: null }],
      ...over,
    },
    tiers: [{ name: "local-small", requires_cloud: false }, { name: "cloud-premium", requires_cloud: true }],
    self_reported: true,
  });
  const renderCost = () => render(<QueryClientProvider client={qc()}><ModeProvider><CostView onSignedOut={() => {}} /></ModeProvider></QueryClientProvider>);

  it("shows cost per task, tier locality and says the figures are self-reported", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(body())));
    renderCost();
    expect(await screen.findByText("$0.02")).toBeInTheDocument();
    expect(screen.getByText(/self-reported/i)).toBeInTheDocument();
    const tiers = screen.getByRole("table", { name: /by tier/i });
    expect(within(tiers.querySelector("tr:nth-child(2)") as HTMLElement).getAllByText(/local|cloud/i).length).toBeGreaterThan(0);
    expect(within(tiers).getByText("cloud")).toBeInTheDocument();
    expect(within(tiers).getByText("local")).toBeInTheDocument();
  });

  it("says so when no task references exist rather than showing $0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(body({ tasks: 0, cost_per_task_usd: null }))));
    renderCost();
    expect(await screen.findByText(/no task references yet/i)).toBeInTheDocument();
  });

  it("renders agent names as inert text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(body())));
    const { container } = renderCost();
    expect(await screen.findByText("<b>evil</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });

  it("builder mode hides token counts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(body())));
    sessionStorage.setItem("promptwise.mode", "builder");
    renderCost();
    await screen.findByText("$0.02");
    expect(screen.queryByText(/tokens in/i)).not.toBeInTheDocument();
  });

  it("changes the window", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => json(body()));
    vi.stubGlobal("fetch", fetchMock);
    renderCost();
    await screen.findByText("$0.02");
    await userEvent.selectOptions(screen.getByLabelText(/window/i), "30");
    await screen.findByText("$0.02");
    expect(fetchMock.mock.calls.map((c) => String(c[0])).some((u) => u.includes("days=30"))).toBe(true);
  });
});
