import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { clearCredential, getCredential } from "./api/credential";
import { TokenGate } from "./features/auth/TokenGate";
import { AuditView } from "./features/audit/AuditView";
import { DiagnosticsView } from "./features/diagnostics/DiagnosticsView";

type Tab = "audit" | "diagnostics";

export default function App() {
  const queryClient = useQueryClient();
  const [authed, setAuthed] = useState(() => getCredential() !== null);
  const [tab, setTab] = useState<Tab>("audit");

  if (!authed) return <TokenGate onAuthed={() => setAuthed(true)} />;

  const signOut = () => {
    clearCredential();
    queryClient.clear(); // the next person at this tab must not see cached data
    setAuthed(false);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <header className="flex items-center justify-between border-b pb-3">
        <span className="font-semibold">PromptWise Agentic OS</span>
        <nav className="flex gap-2 text-sm">
          {(["audit", "diagnostics"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              aria-current={tab === t ? "page" : undefined}
              className={`rounded px-3 py-1 ${tab === t ? "bg-accent text-accent-fg" : "border"}`}
            >
              {t === "audit" ? "Audit" : "Diagnostics"}
            </button>
          ))}
          <button onClick={signOut} className="rounded border px-3 py-1">Sign out</button>
        </nav>
      </header>
      {tab === "audit" ? <AuditView onSignedOut={signOut} /> : <DiagnosticsView onSignedOut={signOut} />}
    </div>
  );
}
