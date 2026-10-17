import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, apiGet } from "../../api/client";
import type { components } from "../../api/schema";
import { Badge } from "../../components/ui";
import { useMode } from "../../mode";

type Usage = components["schemas"]["UsageResponse"];
type Bucket = components["schemas"]["Bucket"];

// Sub-cent costs keep their significant digits ($0.0000004, not $0.0000); large values never use exponent form.
function usd(n: number): string {
  if (!Number.isFinite(n)) return "n/a";
  if (n === 0) return "$0.00";
  const abs = Math.abs(n);
  if (abs < 0.01) return `$${n.toFixed(Math.min(12, 2 - Math.floor(Math.log10(abs)))).replace(/0+$/, "")}`;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function BucketTable({ label, rows, locality, showTokens }: {
  label: string;
  rows: Record<string, Bucket>;
  locality?: Record<string, boolean>;
  showTokens: boolean;
}) {
  const entries = Object.entries(rows).sort((a, b) => b[1].cost_usd - a[1].cost_usd);
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full table-fixed rounded border bg-white text-left text-sm">
        <thead className="bg-slate-100">
          <tr>
            <th className="p-2">{label.replace(/^By /, "")}</th>
            {locality && <th className="w-24 p-2">Runs</th>}
            <th className="w-20 p-2">Events</th>
            {showTokens && <th className="w-32 p-2">Tokens in / out</th>}
            <th className="w-24 p-2">Cost</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, b]) => (
            <tr key={name} className="border-t">
              <td className="break-all p-2">{name}</td>
              {locality && (
                <td className="p-2">
                  {name in locality ? (
                    <Badge tone={locality[name] ? "warn" : "pass"}>{locality[name] ? "cloud" : "local"}</Badge>
                  ) : (
                    <Badge tone="unknown">unknown</Badge>
                  )}
                </td>
              )}
              <td className="p-2">{b.events}</td>
              {showTokens && <td className="p-2">{b.tokens_in} / {b.tokens_out}</td>}
              <td className="p-2">{usd(b.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostView({ onSignedOut }: { onSignedOut: () => void }) {
  const { mode } = useMode();
  const [days, setDays] = useState(7);
  const { data, error, isLoading } = useQuery({
    queryKey: ["usage", days],
    queryFn: ({ signal }) => apiGet<Usage>(`/api/v1/usage?days=${days}`, { signal }),
  });

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) onSignedOut();
  }, [error, onSignedOut]);

  const showTokens = mode === "pro";
  const report = data?.report;
  const locality = data ? Object.fromEntries(data.tiers.map((t) => [t.name, t.requires_cloud])) : undefined;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <h2 className="text-xl font-semibold">Cost and routing</h2>
        <label className="flex flex-col gap-1 text-sm">
          Window
          <select className="rounded border px-2 py-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Last day</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-slate-500">
        Self-reported: figures come from agents calling <code>record_usage</code>. The gateway does not see model traffic,
        so treat them as the agents' own account, not measured spend.
      </p>
      {error && !(error instanceof ApiError && error.status === 401) && (
        <p role="status" className="text-status-block">Could not load usage.</p>
      )}
      {isLoading && <p className="text-slate-500">Loading…</p>}
      {report && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded border bg-white p-3">
              <div className="text-xs text-slate-500">Cost per referenced task</div>
              <div className="text-2xl font-semibold">
                {report.cost_per_task_usd === null ? <span className="text-base text-slate-500">No task references yet</span> : usd(report.cost_per_task_usd)}
              </div>
              <div className="text-xs text-slate-500">{report.tasks} task(s) agents named; not tied to accepted completions</div>
            </div>
            <div className="rounded border bg-white p-3">
              <div className="text-xs text-slate-500">Total cost</div>
              <div className="text-2xl font-semibold">{usd(report.total_cost_usd)}</div>
              <div className="text-xs text-slate-500">{report.events} report(s)</div>
            </div>
            {showTokens && (
              <div className="rounded border bg-white p-3">
                <div className="text-xs text-slate-500">Tokens in / out</div>
                <div className="text-2xl font-semibold">{report.tokens_in} / {report.tokens_out}</div>
              </div>
            )}
          </div>
          <BucketTable label="By tier" rows={report.by_tier} locality={locality} showTokens={showTokens} />
          <BucketTable label="By agent" rows={report.by_agent} showTokens={showTokens} />
          <div>
            <h3 className="mb-2 font-semibold">Recent reports</h3>
            <ul aria-label="Recent usage" className="divide-y rounded border bg-white text-sm">
              {report.recent.map((e) => (
                <li key={e.id} className="flex flex-wrap gap-3 p-2">
                  <span className="break-all font-medium">{e.agent}</span>
                  <span>{e.tier}</span>
                  {e.task_ref && <span className="break-all text-slate-600">{e.task_ref}</span>}
                  <span>{usd(e.cost_usd)}</span>
                </li>
              ))}
            </ul>
            {report.recent.length === 0 && <p className="text-slate-500">No usage reported in this window.</p>}
          </div>
        </>
      )}
    </section>
  );
}
