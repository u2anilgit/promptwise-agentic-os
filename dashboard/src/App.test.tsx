import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { getCredential, setCredential } from "./api/credential";
import { DiagnosticsView } from "./features/diagnostics/DiagnosticsView";
import { TokenGate } from "./features/auth/TokenGate";

function wrap(ui: React.ReactElement) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>;
}

describe("TokenGate", () => {
  it("stores an accepted credential in sessionStorage and continues", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const onAuthed = vi.fn();
    render(<TokenGate onAuthed={onAuthed} />);
    await userEvent.type(screen.getByLabelText(/credential/i), "good-value");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await waitFor(() => expect(onAuthed).toHaveBeenCalled());
    expect(getCredential()).toBe("good-value");
    expect(localStorage.length).toBe(0);
  });

  it("rejects a wrong credential with a clear message and forgets it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const onAuthed = vi.fn();
    render(<TokenGate onAuthed={onAuthed} />);
    await userEvent.type(screen.getByLabelText(/credential/i), "nope");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/not accepted/i)).toBeInTheDocument();
    expect(onAuthed).not.toHaveBeenCalled();
    expect(getCredential()).toBeNull();
  });

  it("tells a server-side credential problem apart from a wrong credential", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    render(<TokenGate onAuthed={() => {}} />);
    await userEvent.type(screen.getByLabelText(/credential/i), "whatever");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/gateway.*credential file/i)).toBeInTheDocument();
  });

  it("does not echo the credential in the clear", () => {
    render(<TokenGate onAuthed={() => {}} />);
    expect(screen.getByLabelText(/credential/i)).toHaveAttribute("type", "password");
  });
});

describe("DiagnosticsView", () => {
  it("maps PASS/WARN/FAIL to labelled pills and renders messages as text", async () => {
    setCredential("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([
      { name: "config.resolve", status: "PASS", message: "ok" },
      { name: "hardware.ram", status: "WARN", message: "low <b>ram</b>" },
      { name: "audit.chain", status: "FAIL", message: "broken" },
    ]), { status: 200 })));
    const { container } = render(wrap(<DiagnosticsView />));
    expect(await screen.findByText("config.resolve")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("WARN")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("low <b>ram</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });
});

describe("source hygiene", () => {
  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return name === "test" ? [] : sources(path);
      return /\.(ts|tsx)$/.test(name) && !/\.test\.|schema\.d\.ts/.test(name) ? [path] : [];
    });
  }
  const files = sources(join(__dirname));

  it.each([
    "dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function(",
  ])("never uses %s", (sink) => {
    const offenders = files.filter((f) => readFileSync(f, "utf8").includes(sink));
    expect(offenders).toEqual([]);
  });

  it("never reads or writes localStorage", () => {
    const offenders = files.filter((f) => /localStorage\s*[.\[]/.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });
});
