import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "../../api/credential";
import { parseRoute } from "../../router";
import { SpecBoard } from "./SpecBoard";

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
);
const summary = (over: Record<string, unknown>) => ({
  spec_id: "s1", request: "login", complexity: "standard", stage: "specified", created_at: 1, tasks_total: 0, tasks_done: 0, ...over,
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => setCredential("tok"));

describe("parseRoute", () => {
  it.each([
    ["", { name: "audit" }],
    ["#/audit", { name: "audit" }],
    ["#/diagnostics", { name: "diagnostics" }],
    ["#/specs", { name: "specs" }],
    ["#/specs/abc-123", { name: "spec", id: "abc-123" }],
    ["#/specs/%E0%A4%A", { name: "specs" }],
    ["#/unknown", { name: "audit" }],
    ["#/specs/", { name: "specs" }],
  ])("%s", (hash, expected) => expect(parseRoute(hash)).toEqual(expected));
});

describe("SpecBoard", () => {
  it("groups specs into stage lanes with task progress", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([
      summary({ spec_id: "a", request: "alpha", stage: "implementing", tasks_total: 4, tasks_done: 1 }),
      summary({ spec_id: "b", request: "beta", stage: "verified", tasks_total: 2, tasks_done: 2 }),
      summary({ spec_id: "c", request: "gamma", stage: "specified" }),
    ])));
    render(wrap(<SpecBoard onOpen={() => {}} onSignedOut={() => {}} />));
    const lane = await screen.findByRole("region", { name: /implementing/i });
    expect(within(lane).getByText("alpha")).toBeInTheDocument();
    expect(within(lane).getByText("1/4 tasks")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /verified/i })).getByText("beta")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^specified/i })).getByText("gamma")).toBeInTheDocument();
  });

  it("puts an unknown stage in an 'other' lane instead of dropping the spec", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([summary({ spec_id: "z", request: "zeta", stage: "archived-v2" })])));
    render(wrap(<SpecBoard onOpen={() => {}} onSignedOut={() => {}} />));
    const lane = await screen.findByRole("region", { name: /other/i });
    expect(within(lane).getByText("zeta")).toBeInTheDocument();
    expect(within(lane).getByText("archived-v2")).toBeInTheDocument();
  });

  it("opens a spec when its card is clicked", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([summary({ spec_id: "s-9", request: "nine" })])));
    const onOpen = vi.fn();
    render(wrap(<SpecBoard onOpen={onOpen} onSignedOut={() => {}} />));
    await userEvent.click(await screen.findByRole("button", { name: /nine/i }));
    expect(onOpen).toHaveBeenCalledWith("s-9");
  });

  it("renders hostile request text inert and wraps long strings", async () => {
    const hostile = '<img src=x onerror="alert(1)">' + "y".repeat(300);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([summary({ request: hostile })])));
    const { container } = render(wrap(<SpecBoard onOpen={() => {}} onSignedOut={() => {}} />));
    const text = await screen.findByText(hostile);
    expect(container.querySelector("img")).toBeNull();
    expect(text.className).toMatch(/break-all|break-words/);
  });

  it("shows an empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([])));
    render(wrap(<SpecBoard onOpen={() => {}} onSignedOut={() => {}} />));
    expect(await screen.findByText(/no specs yet/i)).toBeInTheDocument();
  });

  it("signs out on 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    const onSignedOut = vi.fn();
    render(wrap(<SpecBoard onOpen={() => {}} onSignedOut={onSignedOut} />));
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
  });
});
