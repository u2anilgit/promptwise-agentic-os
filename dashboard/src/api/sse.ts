import type { components } from "./schema";
import { authHeaders } from "./client";
import { clearCredential } from "./credential";

export type AuditRecord = components["schemas"]["AuditRecord"];

export interface SseEvent {
  id?: string;
  event: string;
  data: string;
}

/** Minimal text/event-stream parser: chunk boundaries anywhere, LF or CRLF, comments ignored,
 * multi-line data joined, an event with no terminating blank line is dropped. */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseBlock(block);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseBlock(block: string): SseEvent | null {
  let id: string | undefined;
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":") || line === "") continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { id, event, data: data.join("\n") } : null;
}

export type FeedState = "connecting" | "live" | "reconnecting" | "unauthorized" | "unavailable";

export interface StreamOptions {
  signal: AbortSignal;
  onRecord: (record: AuditRecord) => void;
  onState: (state: FeedState) => void;
  /** Resume cursor (a byte offset from /api/v1/audit's next_cursor); sent as the first Last-Event-ID. */
  after?: string;
  fetchImpl?: typeof fetch;
  retryMs?: number;
}

const SEEN_LIMIT = 2000;

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/** Follow /api/v1/events. The server ends each stream after a while by design; reconnect with
 * Last-Event-ID and drop records already delivered (delivery is at-least-once). */
export async function streamAudit(options: StreamOptions): Promise<void> {
  const { signal, onRecord, onState, fetchImpl = fetch, retryMs = 2000 } = options;
  let lastId: string | undefined = options.after;
  const seen = new Set<string>();
  while (!signal.aborted) {
    onState(lastId === undefined ? "connecting" : "reconnecting");
    try {
      const headers = authHeaders(lastId === undefined ? {} : { "Last-Event-ID": lastId });
      const response = await fetchImpl("/api/v1/events", { headers, signal });
      if (response.status === 401) {
        clearCredential();
        onState("unauthorized");
        return;
      }
      if (response.status === 503) {
        onState("unavailable");
        return;
      }
      if (!response.ok || !response.body) throw new Error(`status ${response.status}`);
      onState("live");
      for await (const event of parseSse(response.body)) {
        if (event.id !== undefined) lastId = event.id;
        if (event.event !== "audit") continue;
        let record: AuditRecord;
        try {
          record = JSON.parse(event.data) as AuditRecord;
        } catch {
          continue;
        }
        if (seen.has(record.id)) continue;
        seen.add(record.id);
        if (seen.size > SEEN_LIMIT) seen.delete(seen.values().next().value as string);
        onRecord(record);
      }
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof Error && error.message === "no credential") {
        onState("unauthorized");
        return;
      }
    }
    if (!signal.aborted) {
      onState("reconnecting");
      await sleep(retryMs, signal);
    }
  }
}
