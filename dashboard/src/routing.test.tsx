import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { setCredential } from "./api/credential";

vi.mock("./api/sse", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api/sse")>();
  return { ...original, streamAudit: vi.fn(async (o: { signal: AbortSignal }) => new Promise<void>((r) => o.signal.addEventListener("abort", () => r()))) };
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const renderApp = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <App />
    </QueryClientProvider>,
  );

beforeEach(() => {
  setCredential("tok");
  window.location.hash = "";
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/history")) return json({ records: [], next_cursor: 0 });
    if (u.includes("/api/v1/specs/")) return json({ detail: "not found" }, 404);
    if (u.includes("/api/v1/specs")) return json([]);
    if (u.includes("/api/v1/diagnostics")) return json([]);
    return json({ records: [], next_cursor: 0, chain: { ok: true, broken_at: null } });
  }));
});

describe("App routing", () => {
  it("shows the audit view by default and falls back to it for unknown hashes", async () => {
    window.location.hash = "#/nonsense";
    renderApp();
    expect(await screen.findByRole("heading", { name: /audit log/i })).toBeInTheDocument();
  });

  it("opens the board from the hash and from the nav", async () => {
    window.location.hash = "#/specs";
    renderApp();
    expect(await screen.findByRole("heading", { name: "Specs" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Diagnostics" }));
    expect(window.location.hash).toBe("#/diagnostics");
    expect(await screen.findByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();
  });

  it("opens a spec detail route and the back button returns to the board", async () => {
    window.location.hash = "#/specs/does-not-exist";
    renderApp();
    expect(await screen.findByText(/spec not found/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /back to specs/i }));
    expect(window.location.hash).toBe("#/specs");
  });
});
