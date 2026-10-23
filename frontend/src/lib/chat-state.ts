import type { AgentResult, ToolCallSummary } from "./types";

export interface LiveToolCall {
  call_id: string;
  tool: string;
  server_id: string | null;
  arguments: Record<string, unknown> | null;
  status: ToolCallSummary["status"] | "running";
  duration_ms?: number;
  attempts?: number;
  error?: string | null;
  cached?: boolean;
}

export interface Turn {
  id: string;
  query: string;
  phase: "connecting" | "discovering" | "thinking" | "calling" | "answering" | "done" | "failed";
  draft: string;
  toolCalls: LiveToolCall[];
  traceId?: string;
  result?: AgentResult;
  error?: { code: string; message: string };
}

export function newTurn(id: string, query: string): Turn {
  return { id, query, phase: "connecting", draft: "", toolCalls: [] };
}

/** Pure reducer applying one backend SSE event to a turn. */
export function applyEvent(turn: Turn, event: string, data: unknown): Turn {
  const d = (data ?? {}) as Record<string, unknown>;
  switch (event) {
    case "start":
      return { ...turn, traceId: String(d.trace_id), phase: "discovering" };
    case "discovery":
      return { ...turn, phase: "thinking" };
    case "llm_start":
      return { ...turn, phase: "thinking" };
    case "token":
      return { ...turn, phase: "answering", draft: turn.draft + String(d.text ?? "") };
    case "answer_reset":
      return { ...turn, draft: "" };
    case "tool_start":
      return {
        ...turn,
        phase: "calling",
        toolCalls: [
          ...turn.toolCalls,
          {
            call_id: String(d.call_id),
            tool: String(d.tool),
            server_id: (d.server_id as string | null) ?? null,
            arguments: (d.arguments as Record<string, unknown> | null) ?? null,
            status: "running",
          },
        ],
      };
    case "tool_end": {
      const s = d as unknown as ToolCallSummary;
      return {
        ...turn,
        toolCalls: turn.toolCalls.map((c) => (c.call_id === s.call_id ? { ...c, ...s } : c)),
      };
    }
    case "error":
      return { ...turn, error: { code: String(d.code), message: String(d.message) } };
    case "final": {
      const result = d as unknown as AgentResult;
      return { ...turn, result, draft: result.answer, phase: "done", toolCalls: result.tool_calls };
    }
    case "done":
      return turn.result ? turn : { ...turn, phase: "failed" };
    default:
      return turn;
  }
}
