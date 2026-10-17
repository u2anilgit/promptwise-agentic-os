import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "../../api/credential";
import { SpecDetail } from "./SpecDetail";

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const status = (over: Record<string, unknown> = {}) => ({
  spec_id: "s1", request: "build login", complexity: "standard", stage: "implementing",
  requirements: [{ id: "R1", text: "The system shall log in users." }, { id: "R2", text: "The system shall log out users." }],
  tasks: [
    { task_id: "t1", status: "done", requirement_ids: ["R1"], depends_on: [], expected_symbols: [], interactive: false, error: null },
    { task_id: "t2", status: "pending", requirement_ids: ["R2"], depends_on: ["t1"], expected_symbols: [], interactive: false, error: null },
  ],
  checks: [
    { requirement_id: "R1", command: "pytest tests/test_login.py", files: ["tests/test_login.py"], expect_baseline: "fail", baseline: "failed", file_hashes: {} },
    { requirement_id: "R2", command: "pytest tests/test_logout.py", files: ["tests/test_logout.py"], expect_baseline: "pass", baseline: "passed", file_hashes: {} },
  ],
  ...over,
});
const entry = (id: string, action: string, result: string, detail: Record<string, unknown>) => ({
  id, timestamp: `2026-10-17T10:00:0${id}+00:00`, actor: "spec_engine", action, target: "s1", result, detail, prev_hash: "p", hash: "h",
});
const history = (records: unknown[]) => ({ records, next_cursor: 1 });

function mockApi(statusBody: unknown, historyBody: unknown, statusCode = 200) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) =>
    String(url).includes("/history") ? json(historyBody) : json(statusBody, statusCode),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const renderDetail = (id = "s1", onSignedOut = () => {}) =>
  render(wrap(<SpecDetail specId={id} onBack={() => {}} onSignedOut={onSignedOut} />));

beforeEach(() => setCredential("tok"));

describe("SpecDetail", () => {
  it("shows requirements, task status and each check's recorded baseline", async () => {
    mockApi(status(), history([]));
    renderDetail();
    expect(await screen.findByText("The system shall log in users.")).toBeInTheDocument();
    const tasks = screen.getByRole("table", { name: /tasks/i });
    expect(within(tasks).getByText("done")).toBeInTheDocument();
    expect(within(tasks).getByText("pending")).toBeInTheDocument();
    const checks = screen.getByRole("table", { name: /checks/i });
    expect(within(checks).getByText(/red before work/i)).toBeInTheDocument();
    expect(within(checks).getByText(/regression guard/i)).toBeInTheDocument();
  });

  it("flags a check whose baseline was never proven", async () => {
    mockApi(status({ checks: [{ requirement_id: "R1", command: "x", files: [], expect_baseline: "fail", baseline: "unverified", file_hashes: {} }] }), history([]));
    renderDetail();
    expect(await screen.findByText(/baseline not proven/i)).toBeInTheDocument();
  });

  it("shows independence layers only from the latest accepted completion of a done task", async () => {
    mockApi(status(), history([
      entry("1", "complete_task", "allow", { task_id: "t1", independence: { baseline_red: true, mutation: false, reviewer: false } }),
      entry("2", "complete_task", "allow", { task_id: "t1", independence: { baseline_red: true, mutation: true, reviewer: true } }),
      entry("3", "complete_task", "allow", { task_id: "t2", independence: { baseline_red: true, mutation: true, reviewer: true } }),
    ]));
    renderDetail();
    const row = (await screen.findByText("t1")).closest("tr")!;
    expect(within(row).getByText("baseline red")).toBeInTheDocument();
    expect(within(row).getByText("mutation")).toBeInTheDocument();
    expect(within(row).getByText("reviewer")).toBeInTheDocument();
    const pendingRow = screen.getByText("t2").closest("tr")!; // pending in core: no layers, whatever the log says
    expect(within(pendingRow).queryByText("mutation")).not.toBeInTheDocument();
  });

  it("lists a denied completion as a denial with its reasons, never as accepted", async () => {
    mockApi(status(), history([entry("1", "complete_task", "deny", { task_id: "t2", reasons: ["checks_failing:R2"] })]));
    renderDetail();
    const timeline = await screen.findByRole("list", { name: /history/i });
    const item = within(timeline).getByText(/complete_task/).closest("li")!;
    expect(within(item).getByText("deny")).toBeInTheDocument();
    expect(within(item).getByText(/checks_failing:R2/)).toBeInTheDocument();
  });

  it("renders hostile text inert and wraps long strings", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    mockApi(status({
      requirements: [{ id: "R1", text: hostile }],
      tasks: [{ task_id: hostile, status: "error", requirement_ids: ["R1"], depends_on: [], expected_symbols: [], interactive: false, error: hostile + "z".repeat(300) }],
      checks: [{ requirement_id: "R1", command: hostile, files: [], expect_baseline: "fail", baseline: "failed", file_hashes: {} }],
    }), history([entry("1", "complete_task", "deny", { task_id: "x", reasons: [hostile] })]));
    const { container } = renderDetail();
    await screen.findAllByText(hostile, { exact: false });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("says 'not found' for an unknown spec and does not spin", async () => {
    mockApi({ detail: "not found" }, history([]), 404);
    renderDetail("nope");
    expect(await screen.findByText(/spec not found/i)).toBeInTheDocument();
  });

  it("signs out on 401", async () => {
    mockApi({}, history([]), 401);
    const onSignedOut = vi.fn();
    renderDetail("s1", onSignedOut);
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
  });

  it("encodes the spec id in request paths", async () => {
    const fetchMock = mockApi(status(), history([]));
    renderDetail("a/b c");
    await screen.findByText("build login");
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.every((u) => u.includes("a%2Fb%20c"))).toBe(true);
  });
});
