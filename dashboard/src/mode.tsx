import { createContext, useContext, useState, type ReactNode } from "react";

// Builder / Pro is progressive disclosure over the same data: it changes wording and how much raw detail is
// shown, never what is fetched, and never hides a warning, a denial or a broken-chain alert.
export type Mode = "builder" | "pro";
const KEY = "promptwise.mode";

function load(): Mode {
  try {
    return sessionStorage.getItem(KEY) === "builder" ? "builder" : "pro";
  } catch {
    return "pro";
  }
}

interface ModeContext {
  mode: Mode;
  setMode: (mode: Mode) => void;
}
const Ctx = createContext<ModeContext>({ mode: load(), setMode: () => {} });

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(load);
  const setMode = (next: Mode) => {
    setModeState(next);
    try {
      sessionStorage.setItem(KEY, next);
    } catch {
      /* the choice just does not survive a reload */
    }
  };
  return <Ctx.Provider value={{ mode, setMode }}>{children}</Ctx.Provider>;
}

export function useMode(): ModeContext {
  return useContext(Ctx);
}

export function ModeToggle() {
  const { mode, setMode } = useMode();
  const button = (value: Mode, label: string) => (
    <button
      onClick={() => setMode(value)}
      aria-pressed={mode === value}
      className={`px-3 py-1 text-sm ${mode === value ? "bg-accent text-accent-fg" : "bg-white"}`}
    >
      {label}
    </button>
  );
  return (
    <div role="group" aria-label="Mode" className="inline-flex overflow-hidden rounded border">
      {button("builder", "Builder")}
      {button("pro", "Pro")}
    </div>
  );
}
