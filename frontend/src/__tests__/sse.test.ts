import { describe, expect, it } from "vitest";

import { parseSSEChunk } from "@/lib/sse";

describe("parseSSEChunk", () => {
  it("parses complete events and keeps the incomplete remainder", () => {
    const text = 'event: start\ndata: {"trace_id":"t1"}\n\nevent: token\ndata: {"text":"Hel';
    const { events, rest } = parseSSEChunk(text);
    expect(events).toEqual([{ event: "start", data: { trace_id: "t1" } }]);
    expect(rest).toBe('event: token\ndata: {"text":"Hel');
    const next = parseSSEChunk(rest + 'lo"}\n\n');
    expect(next.events).toEqual([{ event: "token", data: { text: "Hello" } }]);
  });

  it("ignores keepalive comments, CRLF and malformed JSON", () => {
    const { events } = parseSSEChunk(': keepalive\r\n\r\nevent: x\r\ndata: {bad\r\n\r\nevent: done\r\ndata: {}\r\n\r\n');
    expect(events).toEqual([{ event: "done", data: {} }]);
  });

  it("handles answers containing escaped newlines", () => {
    const { events } = parseSSEChunk('event: token\ndata: {"text":"a\\n\\nb"}\n\n');
    expect(events[0].data).toEqual({ text: "a\n\nb" });
  });
});
