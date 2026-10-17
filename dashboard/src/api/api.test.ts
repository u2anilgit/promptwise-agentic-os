import { describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "./client";
import { clearCredential, getCredential, setCredential } from "./credential";
import { parseSse, streamAudit, type SseEvent } from "./sse";

const enc = new TextEncoder();

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const out: SseEvent[] = [];
  for await (const ev of parseSse(stream)) out.push(ev);
  return out;
}

describe("credential store", () => {
  it("uses sessionStorage only, never localStorage", () => {
    setCredential("abc");
    expect(sessionStorage.getItem("promptwise.credential")).toBe("abc");
    expect(localStorage.length).toBe(0);
    expect(getCredential()).toBe("abc");
    clearCredential();
    expect(getCredential()).toBeNull();
  });
});

describe("apiGet", () => {
  it("sends the bearer header and returns json", async () => {
    setCredential("tok");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await apiGet<{ ok: number }>("/api/v1/policy")).toEqual({ ok: 1 });
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer tok");
  });

  it("clears the credential on 401 and throws ApiError", async () => {
    setCredential("bad");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    await expect(apiGet("/api/v1/policy")).rejects.toMatchObject({ status: 401 });
    expect(getCredential()).toBeNull();
  });

  it("keeps the credential on 503 and reports it distinctly", async () => {
    setCredential("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    const err = (await apiGet("/api/v1/policy").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    expect(getCredential()).toBe("tok");
  });

  it("refuses to call without a credential", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiGet("/api/v1/policy")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("parseSse", () => {
  it("parses events split across chunks, ignoring comments", async () => {
    const events = await collect(
      streamOf([": keepalive\n\nid: 12\nevent: au", 'dit\ndata: {"a":', '1}\n\n']),
    );
    expect(events).toEqual([{ id: "12", event: "audit", data: '{"a":1}' }]);
  });

  it("handles CRLF line endings and multi-line data", async () => {
    const events = await collect(streamOf(["event: audit\r\ndata: one\r\ndata: two\r\n\r\n"]));
    expect(events[0].data).toBe("one\ntwo");
  });

  it("drops a trailing incomplete event", async () => {
    expect(await collect(streamOf(["event: audit\ndata: partial"]))).toEqual([]);
  });
});

describe("streamAudit", () => {
  const record = (id: string) => ({
    id, timestamp: "t", actor: "a", action: "x", target: "y", result: "allow", detail: {}, prev_hash: "p", hash: "h",
  });
  const sse = (id: string, cursor: number) => `id: ${cursor}\nevent: audit\ndata: ${JSON.stringify(record(id))}\n\n`;

  it("reconnects with Last-Event-ID and drops duplicate records", async () => {
    setCredential("tok");
    const calls: Array<Record<string, string>> = [];
    const bodies = [sse("r1", 10) + sse("r2", 20), sse("r2", 20) + sse("r3", 30)];
    const controller = new AbortController();
    const got: string[] = [];
    const fetchMock = vi.fn().mockImplementation(async (_url: string, init: { headers: Record<string, string> }) => {
      calls.push(init.headers);
      const body = bodies.shift();
      if (!body) {
        controller.abort();
        return new Response(streamOf([]), { status: 200 });
      }
      return new Response(streamOf([body]), { status: 200, headers: { "content-type": "text/event-stream" } });
    });
    await streamAudit({
      signal: controller.signal, fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 1,
      onRecord: (r) => got.push(r.id), onState: () => {},
    });
    expect(got).toEqual(["r1", "r2", "r3"]);
    expect(calls[0]["Last-Event-ID"]).toBeUndefined();
    expect(calls[1]["Last-Event-ID"]).toBe("20");
  });

  it("stops and reports unauthorized on 401 without retrying", async () => {
    setCredential("bad");
    const states: string[] = [];
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
    await streamAudit({
      signal: new AbortController().signal, fetchImpl: fetchMock as unknown as typeof fetch, retryMs: 1,
      onRecord: () => {}, onState: (s) => states.push(s),
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(states).toContain("unauthorized");
    expect(getCredential()).toBeNull();
  });
});
