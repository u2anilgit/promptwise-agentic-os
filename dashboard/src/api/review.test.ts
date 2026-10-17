import { describe, expect, it, vi } from "vitest";
import { setCredential } from "./credential";
import { parseSse, streamAudit, type FeedState, type SseEvent } from "./sse";

const enc = new TextEncoder();
const streamOf = (chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(c) {
      for (const x of chunks) c.enqueue(enc.encode(x));
      c.close();
    },
  });
async function collect(chunks: string[]): Promise<SseEvent[]> {
  const out: SseEvent[] = [];
  for await (const e of parseSse(streamOf(chunks))) out.push(e);
  return out;
}
const record = (id: string) => ({
  id, timestamp: "t", actor: "a", action: "x", target: "y", result: "allow", detail: {}, prev_hash: "p", hash: "h",
});

describe("parseSse edge cases", () => {
  it("accepts CR-only line endings, including a CR split from its LF across chunks", async () => {
    expect(await collect(["event: audit\rdata: one\r\r"])).toEqual([{ id: undefined, event: "audit", data: "one" }]);
    expect(await collect(["event: audit\r", "\ndata: two\r", "\n\r", "\n"])).toEqual([
      { id: undefined, event: "audit", data: "two" },
    ]);
  });

  it("keeps an id that arrives without data", async () => {
    const events = await collect(["id: 77\n\n"]);
    expect(events).toEqual([{ id: "77", event: "message", data: "" }]);
  });

  it("accepts data without the optional space", async () => {
    expect((await collect(["data:x\n\n"]))[0].data).toBe("x");
  });
});

describe("streamAudit behaviour", () => {
  it("reports 'connecting' (not 'reconnecting') on the first connect even when resuming from a cursor", async () => {
    setCredential("tok");
    const states: FeedState[] = [];
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(async () => {
      controller.abort();
      return new Response(streamOf([]), { status: 200 });
    });
    await streamAudit({
      signal: controller.signal, after: "123", fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 1,
      onRecord: () => {}, onState: (s) => states.push(s),
    });
    expect(states[0]).toBe("connecting");
  });

  it("uses an id-only event as the resume point", async () => {
    setCredential("tok");
    const headers: Array<Record<string, string>> = [];
    const controller = new AbortController();
    const bodies = ["id: 55\n\n"];
    const fetchMock = vi.fn().mockImplementation(async (_u: string, init: { headers: Record<string, string> }) => {
      headers.push(init.headers);
      const body = bodies.shift();
      if (body === undefined) controller.abort();
      return new Response(streamOf(body ? [body] : []), { status: 200 });
    });
    await streamAudit({
      signal: controller.signal, fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 1,
      onRecord: () => {}, onState: () => {},
    });
    expect(headers[1]["Last-Event-ID"]).toBe("55");
  });

  it("retries a 503 and a 429 with backoff instead of giving up or spinning", async () => {
    setCredential("tok");
    const states: FeedState[] = [];
    const controller = new AbortController();
    const statuses = [503, 429, 200];
    const times: number[] = [];
    const fetchMock = vi.fn().mockImplementation(async () => {
      times.push(Date.now());
      const status = statuses.shift();
      if (status === undefined) { controller.abort(); return new Response(streamOf([]), { status: 200 }); }
      return status === 200
        ? new Response(streamOf([`event: audit\ndata: ${JSON.stringify(record("r1"))}\n\n`]), { status: 200 })
        : new Response("{}", { status });
    });
    const got: string[] = [];
    await streamAudit({
      signal: controller.signal, fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 20,
      onRecord: (r) => got.push(r.id), onState: (s) => states.push(s),
    });
    expect(got).toEqual(["r1"]);
    expect(states).toContain("unavailable");
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(15);
    expect(times[2] - times[1]).toBeGreaterThanOrEqual(30); // doubled
  });

  it("calls onReset when the server says the log was replaced", async () => {
    setCredential("tok");
    const controller = new AbortController();
    const onReset = vi.fn();
    const fetchMock = vi.fn().mockImplementation(async () => {
      controller.abort();
      return new Response(streamOf(["id: 0\nevent: reset\ndata: {}\n\n"]), { status: 200 });
    });
    await streamAudit({
      signal: controller.signal, fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 1,
      onRecord: () => {}, onState: () => {}, onReset,
    });
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
