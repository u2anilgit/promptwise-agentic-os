import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "../../api/credential";
import { parseRoute } from "../../router";
import { SpecDetail } from "./SpecDetail";

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const spec = (tasks: unknown[]) => ({
  spec_id: "s1", request: "r", complexity: "standard", stage: "implementing",
  requirements: [{ id: "R1", text: "t" }], tasks, checks: [],
});
const task = (id: string, status: string) => ({ task_id: id, status, requirement_ids: ["R1"], depends_on: [], expected_symbols: [], interactive: false, error: null });
const entry = (id: string, over: Record<string, unknown> = {}) => ({
  id, timestamp: `2026-10-17T10:00:0${id}+00:00`, actor: "spec_engine", action: "complete_task", target: "s1", result: "allow",
  detail: { task_id: "t1", independence: { baseline_red: true, mutation: true, reviewer: false } }, prev_hash: "p", hash: "h", ...over,
});

function mockApi(specBody: unknown, history: { records: unknown[]; truncated?: boolean }, accepted = history) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/history")) {
      const body = u.includes("action=complete_task") ? accepted : history;
      return json({ next_cursor: 1, truncated: false, ...body });
    }
    return json(specBody);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const renderDetail = () => render(wrap(<SpecDetail specId="s1" onBack={() => {}} onSignedOut={() => {}} />));

beforeEach(() => setCredential("tok"));

describe("acceptance evidence is never silently absent", () => {
  it("reads accepted completions with a dedicated query, so retries cannot push them out of view", async () => {
    const fetchMock = mockApi(spec([task("t1", "done")]), { records: [] }, { records: [entry("1")] });
    renderDetail();
    const tasks = await screen.findByRole("table", { name: /tasks/i });
    expect(await within(tasks).findByText("mutation")).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("action=complete_task") && u.includes("result=allow"))).toBe(true);
  });

  it("says so when a done task has no acceptance record in what was loaded", async () => {
    mockApi(spec([task("t1", "done")]), { records: [] });
    renderDetail();
    const tasks = await screen.findByRole("table", { name: /tasks/i });
    expect(await within(tasks).findByText(/acceptance record not loaded/i)).toBeInTheDocument();
  });

  it("does not claim a record is missing for a pending task", async () => {
    mockApi(spec([task("t1", "pending")]), { records: [] });
    renderDetail();
    const tasks = await screen.findByRole("table", { name: /tasks/i });
    expect(within(tasks).queryByText(/acceptance record not loaded/i)).not.toBeInTheDocument();
  });

  it("tells the reader when the history shown is partial", async () => {
    mockApi(spec([task("t1", "pending")]), { records: [entry("1", { result: "deny" })], truncated: true });
    renderDetail();
    expect(await screen.findByText(/older activity is not shown/i)).toBeInTheDocument();
  });
});

describe("entries that did not come from the spec engine", () => {
  const forged = entry("1", { actor: "mcp" });

  it("never contribute independence layers", async () => {
    mockApi(spec([task("t1", "done")]), { records: [forged] }, { records: [forged] });
    renderDetail();
    const tasks = await screen.findByRole("table", { name: /tasks/i });
    expect(within(tasks).queryByText("mutation")).not.toBeInTheDocument();
    expect(await within(tasks).findByText(/acceptance record not loaded/i)).toBeInTheDocument();
  });

  it("are labelled in the timeline", async () => {
    mockApi(spec([task("t1", "pending")]), { records: [forged] });
    renderDetail();
    const timeline = await screen.findByRole("list", { name: /history/i });
    expect(within(timeline).getByText(/not from the spec engine/i)).toBeInTheDocument();
  });
});

describe("rendering robustness", () => {
  it("does not produce duplicate-key warnings when a denial repeats the same reason", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const dup = entry("1", { result: "deny", detail: { task_id: "t1", reasons: ["acceptance_check_modified:f.py", "acceptance_check_modified:f.py"] } });
    mockApi(spec([task("t1", "pending")]), { records: [dup] });
    renderDetail();
    await screen.findByRole("list", { name: /history/i });
    expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key|unique "key"/i);
    errors.mockRestore();
  });
});

describe("router id validation", () => {
  it.each([
    "#/specs/.", "#/specs/..", "#/specs/a%2Fb", "#/specs/a%20b", "#/specs/" + "x".repeat(65), "#/specs/%00", "#/specs/a%3Fb",
  ])("rejects %s", (hash) => expect(parseRoute(hash)).toEqual({ name: "specs" }));

  it.each(["#/specs/79eabaa65dc5", "#/specs/spec-1_A", "#/specs/" + "x".repeat(64)])("accepts %s", (hash) =>
    expect(parseRoute(hash).name).toBe("spec"),
  );
});
