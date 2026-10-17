import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import { Badge, type Tone } from "../../components/ui";

interface Diagnostic {
  name: string;
  status: "PASS" | "WARN" | "FAIL";
  message: string;
}

// The status is computed by core (`run_diagnostics`); the UI only maps it to a label and tone.
const TONE: Record<Diagnostic["status"], Tone> = { PASS: "pass", WARN: "warn", FAIL: "block" };

export function DiagnosticsView() {
  const { data, error, isFetching, refetch } = useQuery({
    queryKey: ["diagnostics"],
    queryFn: ({ signal }) => apiGet<Diagnostic[]>("/api/v1/diagnostics", { signal }),
  });

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-4">
        <h2 className="text-xl font-semibold">Diagnostics</h2>
        <button className="rounded border px-3 py-1 text-sm" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? "Checking" : "Refresh"}
        </button>
      </div>
      {error && <p role="status" className="text-status-block">Could not load diagnostics.</p>}
      <ul className="divide-y rounded border bg-white">
        {(data ?? []).map((d) => (
          <li key={d.name} className="flex items-start gap-3 p-3">
            <Badge tone={TONE[d.status] ?? "unknown"}>{d.status}</Badge>
            <div className="min-w-0">
              <div className="font-medium break-all">{d.name}</div>
              <div className="text-sm text-slate-600 break-words">{d.message}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
