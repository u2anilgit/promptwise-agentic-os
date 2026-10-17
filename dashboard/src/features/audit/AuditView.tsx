import { useEffect, useRef, useState } from "react";
import { ApiError, apiGet } from "../../api/client";
import type { components } from "../../api/schema";
import { streamAudit, type AuditRecord, type FeedState } from "../../api/sse";
import { Badge } from "../../components/ui";
import { explainAction } from "../../explain";
import { useMode } from "../../mode";

type AuditResponse = components["schemas"]["AuditResponse"];
type Chain = components["schemas"]["ChainStatus"];

const MAX_ROWS = 500;
const TAIL_ROWS = 200;
const RESULT_TONE = { allow: "pass", deny: "block", error: "warn" } as const;

function ChainBanner({ chain, checkedAt }: { chain: Chain; checkedAt: string | null }) {
  if (chain.ok) return <Badge tone="pass" title={`Hash chain checked${checkedAt ? ` at ${checkedAt}` : ""}; re-checked periodically`}>Chain verified</Badge>;
  return (
    <div role="alert" className="rounded border border-status-block bg-red-50 p-3 text-status-block">
      <strong>Audit chain broken</strong> at record {chain.broken_at ?? "unknown"}. The log has been altered or
      damaged since that record; treat everything after it as unverified.
    </div>
  );
}

const FEED_LABEL: Record<FeedState, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  unauthorized: "Signed out",
  unavailable: "Gateway credential unavailable",
};

export function AuditView({ onSignedOut, chainPollMs = 15000 }: { onSignedOut?: () => void; chainPollMs?: number }) {
  const { mode } = useMode();
  const [actionInput, setActionInput] = useState("");
  const [action, setAction] = useState("");
  const [result, setResult] = useState("");
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [chain, setChain] = useState<Chain | null>(null);
  const [feed, setFeed] = useState<FeedState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const signedOut = useRef(onSignedOut);
  signedOut.current = onSignedOut;

  useEffect(() => {
    const timer = setTimeout(() => setAction(actionInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [actionInput]);

  // The verdict is only as fresh as its last check: re-ask while the tab stays open, so tampering that
  // happens after the page loaded still raises the alarm.
  useEffect(() => {
    const timer = setInterval(() => {
      apiGet<AuditResponse>("/api/v1/audit?limit=1&tail=true")
        .then((page) => { setChain(page.chain); setCheckedAt(new Date().toLocaleTimeString()); })
        .catch((e) => { if (e instanceof ApiError && e.status === 401) signedOut.current?.(); });
    }, chainPollMs);
    return () => clearInterval(timer);
  }, [chainPollMs]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setError(null);
    setRecords([]);
    setChain(null);
    const query = new URLSearchParams({ tail: "true", limit: String(TAIL_ROWS) });
    if (action) query.set("action", action);
    if (result) query.set("result", result);

    const matches = (r: AuditRecord) => (!action || r.action === action) && (!result || r.result === result);

    (async () => {
      let page: AuditResponse;
      try {
        page = await apiGet<AuditResponse>(`/api/v1/audit?${query}`, { signal });
      } catch (e) {
        if (signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) signedOut.current?.();
        else setError(e instanceof ApiError && e.status === 503 ? "The gateway's credential file is unusable; check its logs." : "Could not load the audit log.");
        return;
      }
      if (signal.aborted) return;
      setRecords([...page.records].reverse());
      setChain(page.chain);
      setCheckedAt(new Date().toLocaleTimeString());
      await streamAudit({
        signal,
        after: String(page.next_cursor),
        onReset: () => { if (!signal.aborted) setRecords([]); },
        onState: (state) => {
          if (signal.aborted) return;
          setFeed(state);
          if (state === "unauthorized") signedOut.current?.();
        },
        onRecord: (record) => {
          if (signal.aborted || !matches(record)) return;
          setRecords((current) =>
            current.some((r) => r.id === record.id) ? current : [record, ...current].slice(0, MAX_ROWS),
          );
        },
      });
    })();

    return () => controller.abort();
  }, [action, result]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <h2 className="text-xl font-semibold">Audit log</h2>
        {chain && <ChainBanner chain={chain} checkedAt={checkedAt} />}
        <Badge tone={feed === "live" ? "pass" : feed === "connecting" || feed === "reconnecting" ? "warn" : "block"}>
          {FEED_LABEL[feed]}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex flex-col gap-1">
          Action
          <input className="rounded border px-2 py-1" value={actionInput} onChange={(e) => setActionInput(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          Result
          <select className="rounded border px-2 py-1" value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="">any</option>
            <option value="allow">allow</option>
            <option value="deny">deny</option>
            <option value="error">error</option>
          </select>
        </label>
      </div>

      {error && <p role="status" className="text-status-block">{error}</p>}

      <div className="overflow-x-auto rounded border bg-white">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="w-48 p-2">Time</th>
              <th className="w-28 p-2">Actor</th>
              <th className="w-40 p-2">Action</th>
              <th className="p-2">Target</th>
              <th className="w-24 p-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="p-2 break-all">{r.timestamp}</td>
                <td className="p-2 break-all">{r.actor}</td>
                <td className="p-2 break-all" title={mode === "builder" ? r.action : undefined}>
                  {(mode === "builder" && explainAction(r.action, r.result)) || r.action}
                </td>
                <td className="p-2 break-all">
                  {r.target}
                  {mode === "pro" && Object.keys(r.detail).length > 0 && (
                    <details className="mt-1 text-xs text-slate-600">
                      <summary className="cursor-pointer">detail</summary>
                      <pre className="whitespace-pre-wrap break-all">{JSON.stringify(r.detail, null, 2)}</pre>
                    </details>
                  )}
                </td>
                <td className="p-2">
                  <Badge tone={RESULT_TONE[r.result]}>{r.result}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {records.length === 0 && !error && <p className="p-4 text-slate-500">No audit records yet.</p>}
      </div>
    </section>
  );
}
