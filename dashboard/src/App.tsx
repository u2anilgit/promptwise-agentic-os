import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { clearCredential, getCredential } from "./api/credential";
import { TokenGate } from "./features/auth/TokenGate";
import { AuditView } from "./features/audit/AuditView";
import { DiagnosticsView } from "./features/diagnostics/DiagnosticsView";
import { CostView } from "./features/cost/CostView";
import { ModeToggle } from "./mode";
import { SpecBoard } from "./features/specs/SpecBoard";
import { SpecDetail } from "./features/specs/SpecDetail";
import { hrefFor, navigate, useRoute } from "./router";

const NAV = [
  { name: "audit", label: "Audit" },
  { name: "specs", label: "Specs" },
  { name: "cost", label: "Cost" },
  { name: "diagnostics", label: "Diagnostics" },
] as const;

export default function App() {
  const queryClient = useQueryClient();
  const route = useRoute();
  const [authed, setAuthed] = useState(() => getCredential() !== null);

  if (!authed) return <TokenGate onAuthed={() => setAuthed(true)} />;

  const signOut = () => {
    clearCredential();
    queryClient.clear(); // the next person at this tab must not see cached data
    setAuthed(false);
  };
  const section = route.name === "spec" ? "specs" : route.name;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <header className="flex items-center justify-between border-b pb-3">
        <span className="font-semibold">PromptWise Agentic OS</span>
        <nav className="flex flex-wrap items-center gap-2 text-sm">
          <ModeToggle />
          {NAV.map((item) => (
            <a
              key={item.name}
              href={hrefFor({ name: item.name })}
              aria-current={section === item.name ? "page" : undefined}
              className={`rounded px-3 py-1 ${section === item.name ? "bg-accent text-accent-fg" : "border"}`}
            >
              {item.label}
            </a>
          ))}
          <button onClick={signOut} className="rounded border px-3 py-1">Sign out</button>
        </nav>
      </header>
      {route.name === "audit" && <AuditView onSignedOut={signOut} />}
      {route.name === "cost" && <CostView onSignedOut={signOut} />}
      {route.name === "diagnostics" && <DiagnosticsView onSignedOut={signOut} />}
      {route.name === "specs" && (
        <SpecBoard onOpen={(id) => navigate({ name: "spec", id })} onSignedOut={signOut} />
      )}
      {route.name === "spec" && (
        <SpecDetail specId={route.id} onBack={() => navigate({ name: "specs" })} onSignedOut={signOut} />
      )}
    </div>
  );
}
