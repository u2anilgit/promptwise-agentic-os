import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, apiGet } from "../../api/client";
import type { components } from "../../api/schema";
import { Badge } from "../../components/ui";

export type SpecSummary = components["schemas"]["SpecSummary"];

// Lanes follow the spec engine's stage order. A stage this UI does not know yet goes to "other"
// rather than being dropped, so a newer core never makes work invisible.
export const STAGES = ["specified", "planned", "tasked", "implementing", "verified"] as const;

interface Props {
  onOpen: (specId: string) => void;
  onSignedOut: () => void;
}

export function SpecBoard({ onOpen, onSignedOut }: Props) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["specs"],
    queryFn: ({ signal }) => apiGet<SpecSummary[]>("/api/v1/specs", { signal }),
  });

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) onSignedOut();
  }, [error, onSignedOut]);

  const specs = data ?? [];
  const known = new Set<string>(STAGES);
  const lanes = [
    ...STAGES.map((stage) => ({ stage: stage as string, items: specs.filter((s) => s.stage === stage) })),
    { stage: "other", items: specs.filter((s) => !known.has(s.stage)) },
  ].filter((lane) => lane.items.length > 0 || lane.stage !== "other");

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Specs</h2>
      {error && !(error instanceof ApiError && error.status === 401) && (
        <p role="status" className="text-status-block">Could not load specs.</p>
      )}
      {!isLoading && !error && specs.length === 0 && <p className="text-slate-500">No specs yet.</p>}
      {isLoading && <p className="text-slate-500">Loading specs…</p>}
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        {!isLoading && lanes.map((lane) => (
          <section key={lane.stage} aria-label={lane.stage} className="min-w-0 space-y-2 rounded bg-slate-100 p-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              {lane.stage} ({lane.items.length})
            </h3>
            {lane.items.map((s) => (
              <button
                key={s.spec_id}
                onClick={() => onOpen(s.spec_id)}
                className="block w-full min-w-0 rounded border bg-white p-2 text-left text-sm shadow-sm hover:border-accent"
              >
                <span className="block break-all font-medium">{s.request}</span>
                <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                  <Badge tone={s.stage === "verified" ? "pass" : "unknown"}>{s.stage}</Badge>
                  <span>{`${s.tasks_done}/${s.tasks_total} tasks`}</span>
                  <span>{s.complexity}</span>
                </span>
              </button>
            ))}
          </section>
        ))}
      </div>
    </section>
  );
}
