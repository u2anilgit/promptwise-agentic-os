import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError, apiGet } from "../../api/client";
import type { components } from "../../api/schema";
import { Badge, type Tone } from "../../components/ui";

type SpecStatus = components["schemas"]["SpecStatus"];
type AuditRecord = components["schemas"]["AuditRecord"];
type History = components["schemas"]["AuditPage"];

const TASK_TONE: Record<string, Tone> = { done: "pass", pending: "unknown", error: "block" };
const BASELINE: Record<string, { label: string; tone: Tone }> = {
  failed: { label: "red before work", tone: "pass" },
  passed: { label: "regression guard (passed before work)", tone: "warn" },
  unverified: { label: "baseline not proven", tone: "block" },
};
const LAYERS: Array<[string, string]> = [
  ["baseline_red", "baseline red"],
  ["mutation", "mutation"],
  ["reviewer", "reviewer"],
];

const ENGINE = "spec_engine";

/** The layers behind a task's acceptance are read from the spec engine's own audit entry for its latest
 * accepted completion; nothing is recomputed here. `null` means the task is done in core but no such
 * entry was loaded: that is "record not loaded", never "accepted with nothing". Entries written by any
 * other actor are ignored. */
function layersFor(taskId: string, records: AuditRecord[]): string[] | null {
  for (let i = records.length - 1; i >= 0; i--) {
    const r = records[i];
    if (r.actor !== ENGINE || r.action !== "complete_task" || r.result !== "allow" || r.detail.task_id !== taskId) continue;
    const independence = r.detail.independence;
    if (independence && typeof independence === "object") {
      return LAYERS.filter(([key]) => (independence as Record<string, unknown>)[key] === true).map(([, label]) => label);
    }
    return [];
  }
  return null;
}

function reasonsOf(record: AuditRecord): string[] {
  const reasons = record.detail.reasons;
  return Array.isArray(reasons) ? reasons.filter((r): r is string => typeof r === "string") : [];
}

function AcceptedWith({ layers, loading }: { layers: string[] | null; loading: boolean }) {
  if (loading) return null;
  if (layers === null) return <Badge tone="warn">acceptance record not loaded</Badge>;
  if (layers.length === 0) return <span className="text-xs text-slate-500">no independent layers</span>;
  return <>{layers.map((label) => <Badge key={label} tone="pass">{label}</Badge>)}</>;
}

interface Props {
  specId: string;
  onBack: () => void;
  onSignedOut: () => void;
}

const RESULT_TONE: Record<string, Tone> = { allow: "pass", deny: "block", error: "warn" };

export function SpecDetail({ specId, onBack, onSignedOut }: Props) {
  const encoded = encodeURIComponent(specId);
  const spec = useQuery({
    queryKey: ["spec", specId],
    queryFn: ({ signal }) => apiGet<SpecStatus>(`/api/v1/specs/${encoded}`, { signal }),
  });
  const history = useQuery({
    queryKey: ["spec-history", specId],
    queryFn: ({ signal }) => apiGet<History>(`/api/v1/specs/${encoded}/history?limit=200`, { signal }),
    staleTime: 10_000,
  });
  // Accepted completions get their own narrow query: a long run of denied retries must not push them out.
  const accepted = useQuery({
    queryKey: ["spec-accepted", specId],
    queryFn: ({ signal }) =>
      apiGet<History>(`/api/v1/specs/${encoded}/history?limit=200&action=complete_task&result=allow`, { signal }),
    staleTime: 10_000,
  });

  useEffect(() => {
    const signedOut = [spec.error, history.error, accepted.error].some((e) => e instanceof ApiError && e.status === 401);
    if (signedOut) onSignedOut();
  }, [spec.error, history.error, accepted.error, onSignedOut]);

  const back = (
    <button onClick={onBack} className="rounded border px-3 py-1 text-sm">Back to specs</button>
  );

  if (spec.error instanceof ApiError && spec.error.status === 404) {
    return <section className="space-y-4">{back}<p>Spec not found.</p></section>;
  }
  if (spec.error) {
    return <section className="space-y-4">{back}<p role="status" className="text-status-block">Could not load this spec.</p></section>;
  }
  if (!spec.data) return <section className="space-y-4">{back}<p className="text-slate-500">Loading…</p></section>;

  const s = spec.data;
  const records = history.data?.records ?? [];
  const acceptedRecords = accepted.data?.records ?? [];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {back}
        <h2 className="min-w-0 break-all text-xl font-semibold">{s.request}</h2>
        <Badge tone={s.stage === "verified" ? "pass" : "unknown"}>{s.stage}</Badge>
        <span className="text-sm text-slate-600">{s.complexity}</span>
      </div>

      <div>
        <h3 className="mb-2 font-semibold">Requirements</h3>
        <ul className="divide-y rounded border bg-white">
          {s.requirements.map((r) => (
            <li key={r.id} className="flex gap-3 p-2 text-sm">
              <span className="font-mono text-slate-500">{r.id}</span>
              <span className="min-w-0 break-words">{r.text}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="overflow-x-auto">
        <h3 className="mb-2 font-semibold">Tasks</h3>
        <table aria-label="Tasks" className="w-full table-fixed rounded border bg-white text-left text-sm">
          <thead className="bg-slate-100">
            <tr><th className="p-2">Task</th><th className="w-24 p-2">Status</th><th className="p-2">Requirements</th><th className="p-2">Depends on</th><th className="p-2">Accepted with</th></tr>
          </thead>
          <tbody>
            {s.tasks.map((t) => (
              <tr key={t.task_id} className="border-t align-top">
                <td className="break-all p-2">
                  {t.task_id}
                  {t.error && <div className="mt-1 break-all text-xs text-status-block">{t.error}</div>}
                </td>
                <td className="p-2"><Badge tone={TASK_TONE[t.status] ?? "unknown"}>{t.status}</Badge></td>
                <td className="break-all p-2">{t.requirement_ids.join(", ")}</td>
                <td className="break-all p-2">{t.depends_on.join(", ") || "none"}</td>
                <td className="space-x-1 p-2">
                  {t.status === "done" && <AcceptedWith layers={layersFor(t.task_id, acceptedRecords)} loading={accepted.isLoading} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto">
        <h3 className="mb-2 font-semibold">Acceptance checks</h3>
        <table aria-label="Checks" className="w-full table-fixed rounded border bg-white text-left text-sm">
          <thead className="bg-slate-100">
            <tr><th className="w-20 p-2">Req</th><th className="p-2">Command</th><th className="w-56 p-2">Baseline</th></tr>
          </thead>
          <tbody>
            {s.checks.map((c) => {
              const b = BASELINE[c.baseline] ?? { label: c.baseline, tone: "unknown" as Tone };
              return (
                <tr key={`${c.requirement_id}-${c.command}`} className="border-t align-top">
                  <td className="p-2">{c.requirement_id}</td>
                  <td className="break-all p-2 font-mono text-xs">{c.command}</td>
                  <td className="p-2"><Badge tone={b.tone}>{b.label}</Badge></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div>
        <h3 className="mb-2 font-semibold">History</h3>
        {history.error && !(history.error instanceof ApiError && history.error.status === 401) && (
          <p role="status" className="text-status-block">Could not load history.</p>
        )}
        <ul aria-label="History" className="divide-y rounded border bg-white text-sm">
          {[...records].reverse().map((r) => (
            <li key={r.id} className="space-y-1 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-slate-500">{r.timestamp}</span>
                <span className="font-medium">{r.action}</span>
                <Badge tone={RESULT_TONE[r.result] ?? "unknown"}>{r.result}</Badge>
                {typeof r.detail.task_id === "string" && <span className="break-all text-slate-600">{r.detail.task_id}</span>}
                {r.actor !== ENGINE && <Badge tone="warn">not from the spec engine</Badge>}
              </div>
              {reasonsOf(r).map((reason, index) => (
                <div key={`${index}-${reason}`} className="break-all text-status-block">{reason}</div>
              ))}
              {Object.keys(r.detail).length > 0 && (
                <details className="text-xs text-slate-600">
                  <summary className="cursor-pointer">detail</summary>
                  <pre className="whitespace-pre-wrap break-all">{JSON.stringify(r.detail, null, 2)}</pre>
                </details>
              )}
            </li>
          ))}
        </ul>
        {history.data?.truncated && (
          <p className="text-xs text-slate-500">Older activity is not shown (the most recent {records.length} entries are listed).</p>
        )}
        {records.length === 0 && !history.error && <p className="text-slate-500">No recorded activity.</p>}
      </div>
    </section>
  );
}
