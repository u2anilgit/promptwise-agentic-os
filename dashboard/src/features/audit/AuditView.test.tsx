import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCredential } from "../../api/credential";
import type { AuditRecord, StreamOptions } from "../../api/sse";
import { AuditView } from "./AuditView";

let pushRecord: (r: AuditRecord) => void = () => {};
let streamArgs: Partial<StreamOptions> = {};

vi.mock("../../api/sse", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/sse")>();
  return {
    ...original,
    streamAudit: vi.fn(async (options: StreamOptions) => {
      streamArgs = options;
      pushRecord = options.onRecord;
      options.onState("live");
      await new Promise<void>((resolve) => options.signal.addEventListener("abort", () => resolve()));
    }),
  };
});

const rec = (id: string, over: Partial<AuditRecord> = {}): AuditRecord => ({
  id, timestamp: "2026-10-17T10:00:00+00:00", actor: "mcp", action: "tool_call", target: `target-${id}`,
  result: "allow", detail: {}, prev_hash: "p", hash: "h", ...over,
});

function mockTail(records: AuditRecord[], chain = { ok: true, broken_at: null as number | null }) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ records, next_cursor: 123, chain }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => setCredential("tok"));

describe("AuditView", () => {
  it("shows the tail newest first and a healthy chain", async () => {
    mockTail([rec("a"), rec("b")]);
    render(<AuditView />);
    expect(await screen.findByText("target-b")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("target-b");
    expect(rows[1]).toHaveTextContent("target-a");
    expect(screen.getByText(/chain verified/i)).toBeInTheDocument();
  });

  it("starts the live feed from the tail's cursor so nothing is missed in between", async () => {
    mockTail([rec("a")]);
    render(<AuditView />);
    await screen.findByText("target-a");
    await waitFor(() => expect(streamArgs.after).toBe("123"));
  });

  it("prepends a live record exactly once", async () => {
    mockTail([rec("a")]);
    render(<AuditView />);
    await screen.findByText("target-a");
    act(() => { pushRecord(rec("z")); pushRecord(rec("z")); });
    expect(screen.getAllByText("target-z")).toHaveLength(1);
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("target-z");
  });

  it("caps the list so a long-open tab cannot grow without bound", async () => {
    mockTail([]);
    render(<AuditView />);
    await waitFor(() => expect(streamArgs.onRecord).toBeDefined());
    act(() => { for (let i = 0; i < 520; i++) pushRecord(rec(`r${i}`)); });
    expect(screen.getAllByRole("row").length - 1).toBe(500);
    expect(screen.queryByText("target-r0")).not.toBeInTheDocument();
    expect(screen.getByText("target-r519")).toBeInTheDocument();
  });

  it("shows a prominent banner naming the broken record", async () => {
    mockTail([rec("a")], { ok: false, broken_at: 41 });
    render(<AuditView />);
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/chain broken/i);
    expect(banner).toHaveTextContent("41");
  });

  it("renders hostile strings as inert text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    mockTail([rec("h", { target: hostile, actor: hostile, detail: { note: hostile } })]);
    const { container } = render(<AuditView />);
    await screen.findAllByText(hostile, { exact: false });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("wraps long unbroken strings instead of overflowing", async () => {
    mockTail([rec("l", { target: "x".repeat(500) })]);
    render(<AuditView />);
    const cell = await screen.findByText("x".repeat(500));
    expect(cell.className).toMatch(/break-all/);
  });

  it("refetches with the chosen filters", async () => {
    const fetchMock = mockTail([rec("a")]);
    render(<AuditView />);
    await screen.findByText("target-a");
    await userEvent.selectOptions(screen.getByLabelText(/result/i), "deny");
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes("result=deny") && u.includes("tail=true"))).toBe(true);
    });
  });

  it("explains a rejected credential instead of looping", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const onSignedOut = vi.fn();
    render(<AuditView onSignedOut={onSignedOut} />);
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
  });
});
