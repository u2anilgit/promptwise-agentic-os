import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "../api/credential";
import type { AuditRecord, StreamOptions } from "../api/sse";
import { AuditView } from "./audit/AuditView";
import { DiagnosticsView } from "./diagnostics/DiagnosticsView";

let latest: StreamOptions | null = null;
vi.mock("../api/sse", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/sse")>();
  return {
    ...original,
    streamAudit: vi.fn(async (options: StreamOptions) => {
      latest = options;
      options.onState("live");
      await new Promise<void>((resolve) => options.signal.addEventListener("abort", () => resolve()));
    }),
  };
});

const rec = (id: string): AuditRecord => ({
  id, timestamp: "t", actor: "a", action: "x", target: `target-${id}`, result: "allow", detail: {}, prev_hash: "p", hash: "h",
});
const page = (records: AuditRecord[], chain = { ok: true, broken_at: null as number | null }) =>
  new Response(JSON.stringify({ records, next_cursor: 5, chain }), { status: 200 });

beforeEach(() => {
  setCredential("tok");
  latest = null;
});

describe("AuditView review fixes", () => {
  it("re-checks the chain while the tab stays open and raises the alarm if it breaks", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => page([rec("a")]))
      .mockImplementationOnce(async () => page([rec("a")]))
      .mockImplementationOnce(async () => page([rec("a")]))
      .mockImplementation(async () => page([rec("a")], { ok: false, broken_at: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AuditView chainPollMs={400} />);
    expect(await screen.findByText(/chain verified/i)).toBeInTheDocument();
    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent(/broken at record 3/i);
  });

  it("clears the table when the server announces the log was replaced", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => page([rec("old")])));
    render(<AuditView chainPollMs={100000} />);
    await screen.findByText("target-old");
    act(() => latest!.onReset?.());
    expect(screen.queryByText("target-old")).not.toBeInTheDocument();
  });

  it("does not keep showing the previous filter's rows while a new filter loads or fails", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => page([rec("old")]))
      .mockImplementation(async () => new Response("{}", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AuditView chainPollMs={100000} />);
    await screen.findByText("target-old");
    await userEvent.selectOptions(screen.getByLabelText(/result/i), "deny");
    await waitFor(() => expect(screen.queryByText("target-old")).not.toBeInTheDocument());
    expect(await screen.findByText(/could not load/i)).toBeInTheDocument();
  });

  it("labels the badge with what it actually attests", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => page([])));
    render(<AuditView chainPollMs={100000} />);
    expect(await screen.findByText(/chain verified/i)).toHaveAttribute("title", expect.stringMatching(/checked/i));
  });
});

describe("DiagnosticsView review fixes", () => {
  it("signs out when the credential is rejected instead of looping on a dead session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const onSignedOut = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <DiagnosticsView onSignedOut={onSignedOut} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
  });
});
