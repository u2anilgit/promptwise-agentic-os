import type { components } from "./schema";
import { authHeaders } from "./client";
import { clearCredential } from "./credential";

export type AuditRecord = components["schemas"]["AuditRecord"];

export interface SseEvent {
  id?: string;
  event: string;
  data: string;
}

/** Minimal text/event-stream parser: chunk boundaries anywhere, LF / CRLF / CR line endings (a CR may be
 * split from its LF across chunks), comments ignored, multi-line data joined, an event with an id but no
 * data still reports its id, an event with no terminating blank line is dropped. */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let carry = ""; // a trailing CR waits for the next chunk: it may be half of a CRLF

  function* drain(): Generator<SseEvent> {
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseBlock(block);
      if (parsed) yield parsed;
      boundary = buffer.indexOf("\n\n");
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        if (carry) {
          buffer += "\n";
          carry = "";
          yield* drain();
        }
        return;
      }
      let text = carry + decoder.decode(value, { stream: true });
      carry = "";
      if (text.endsWith("\r")) {
        carry = "\r";
        text = text.slice(0, -1);
      }
      buffer += text.replace(/\r\n?/g, "\n");
      yield* drain();
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
  if (!data.length && id === undefined) return null;
  return { id, event, data: data.join("\n") };
}

export type FeedState = "connecting" | "live" | "reconnecting" | "unauthorized" | "unavailable";

export interface StreamOptions {
  signal: AbortSignal;
  onRecord: (record: AuditRecord) => void;
  onState: (state: FeedState) => void;
  /** The server says the log was replaced by a shorter one: drop what was shown and start over. */
  onReset?: () => void;
  /** Resume cursor (a byte offset from /api/v1/audit's next_cursor); sent as the first Last-Event-ID. */
  after?: string;
  fetchImpl?: typeof fetch;
  retryMs?: number;
}

const SEEN_LIMIT = 2000;
const MAX_BACKOFF_MS = 30_000;

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/** Follow /api/v1/events. The server ends each stream after a while by design; reconnect with
 * Last-Event-ID and drop records already delivered (delivery is at-least-once). Failures (5xx, 429,
 * network) back off exponentially; only a rejected credential stops the loop. */
export async function streamAudit(options: StreamOptions): Promise<void> {
  const { signal, onRecord, onState, onReset, fetchImpl = fetch, retryMs = 2000 } = options;
  let lastId: string | undefined = options.after;
  let attempts = 0;
  let failures = 0;
  const seen = new Set<string>();
  while (!signal.aborted) {
    onState(attempts === 0 ? "connecting" : "reconnecting");
    attempts += 1;
    let failed = false;
    let unavailable = false;
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
        failed = true;
        unavailable = true;
      } else if (!response.ok || !response.body) {
        failed = true;
      } else {
        failures = 0;
        onState("live");
        for await (const event of parseSse(response.body)) {
          if (event.id !== undefined) lastId = event.id;
          if (event.event === "reset") {
            seen.clear();
            onReset?.();
            continue;
          }
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
      }
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof Error && error.message === "no credential") {
        onState("unauthorized");
        return;
      }
      failed = true;
    }
    if (signal.aborted) return;
    if (failed) failures += 1;
    if (!unavailable) onState("reconnecting");
    const delay = failures === 0 ? retryMs : Math.min(retryMs * 2 ** (failures - 1), MAX_BACKOFF_MS);
    await sleep(delay, signal);
  }
}
