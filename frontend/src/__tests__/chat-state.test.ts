import { describe, expect, it } from "vitest";

import { applyEvent, newTurn } from "@/lib/chat-state";
import type { AgentResult } from "@/lib/types";

const final: Partial<AgentResult> = {
  trace_id: "t1",
  answer: "Final answer",
  status: "ok",
  tool_calls: [
    { call_id: "c1", tool: "library__search_books", server_id: "library", arguments: { query: "x" }, status: "success", duration_ms: 40, attempts: 1, error: null, cached: false },
  ],
  citations: [],
  sources: [],
  warnings: [],
};

describe("applyEvent", () => {
  it("walks a turn from start to final", () => {
    let t = newTurn("1", "q");
    t = applyEvent(t, "start", { trace_id: "t1" });
    expect(t.phase).toBe("discovering");
    t = applyEvent(t, "tool_start", { call_id: "c1", tool: "library__search_books", server_id: "library", arguments: { query: "x" } });
    expect(t.toolCalls[0].status).toBe("running");
    t = applyEvent(t, "tool_end", { call_id: "c1", status: "success", duration_ms: 40, attempts: 1 });
    expect(t.toolCalls[0]).toMatchObject({ status: "success", duration_ms: 40, tool: "library__search_books" });
    t = applyEvent(t, "token", { text: "Fin" });
    t = applyEvent(t, "token", { text: "al" });
    expect(t.draft).toBe("Final");
    t = applyEvent(t, "final", final);
    expect(t.phase).toBe("done");
    expect(t.draft).toBe("Final answer");
    expect(applyEvent(t, "done", {}).phase).toBe("done");
  });

  it("drops pre-tool chatter on answer_reset", () => {
    let t = applyEvent(newTurn("1", "q"), "token", { text: "Let me check" });
    t = applyEvent(t, "answer_reset", {});
    expect(t.draft).toBe("");
  });

  it("marks a turn failed if the stream ends without a final result", () => {
    const t = applyEvent(applyEvent(newTurn("1", "q"), "error", { code: "internal_error", message: "boom" }), "done", {});
    expect(t.phase).toBe("failed");
    expect(t.error?.code).toBe("internal_error");
  });
});
