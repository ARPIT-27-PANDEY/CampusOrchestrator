import { Check, Clock, Loader2, RotateCcw, X } from "lucide-react";

import type { LiveToolCall } from "@/lib/chat-state";
import { serviceMeta } from "@/lib/services";
import { cn, formatMs, splitTool } from "@/lib/utils";

const FAILED = new Set(["timeout", "unavailable", "protocol_error", "tool_error", "invalid_arguments", "unknown_tool", "budget_exceeded"]);

function statusText(c: LiveToolCall): string {
  switch (c.status) {
    case "running":
      return "Running";
    case "success":
      return c.cached ? "Reused earlier result" : "Answered";
    case "timeout":
      return "Timed out";
    case "unavailable":
      return "Unreachable";
    case "tool_error":
      return "Returned an error";
    case "invalid_arguments":
      return "Rejected arguments";
    case "unknown_tool":
      return "Unknown tool";
    case "budget_exceeded":
      return "Skipped: tool budget reached";
    default:
      return "Protocol error";
  }
}

function argSummary(args: Record<string, unknown> | null): string {
  if (!args) return "";
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? `"${v}"` : JSON.stringify(v)}`)
    .join(", ");
}

/**
 * The route an answer took through campus systems, drawn like a transit line.
 * Each stop is one MCP tool call, coloured by the system that owns it.
 */
export function ToolRoute({ calls, finished }: { calls: LiveToolCall[]; finished: boolean }) {
  if (!calls.length) {
    return (
      <p className="text-[13px] text-ink-muted">
        {finished ? "Answered without calling any campus system." : "Choosing which systems to ask…"}
      </p>
    );
  }
  return (
    <ol className="relative" aria-label="Tools called for this answer">
      {calls.map((c, i) => {
        const svc = serviceMeta(c.server_id ?? splitTool(c.tool).server);
        const failed = FAILED.has(c.status);
        const last = i === calls.length - 1;
        return (
          <li key={c.call_id} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && <span aria-hidden className="absolute top-6 bottom-0 left-[11px] w-0.5 bg-rule" />}
            <span
              aria-hidden
              className={cn(
                "relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border-2 bg-panel",
              )}
              style={{ borderColor: failed ? "var(--bad)" : svc.color, background: c.status === "success" ? svc.color : undefined }}
            >
              {c.status === "running" && <Loader2 className="size-3.5 animate-spin" style={{ color: svc.color }} />}
              {c.status === "success" && (c.cached ? <RotateCcw className="size-3 text-panel" /> : <Check className="size-3.5 text-panel" />)}
              {c.status === "timeout" && <Clock className="size-3.5 text-bad" />}
              {failed && c.status !== "timeout" && <X className="size-3.5 text-bad" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-medium">
                  {svc.name} <span className="font-normal text-ink-muted">{splitTool(c.tool).tool}</span>
                </p>
                {c.duration_ms != null && c.status !== "running" && (
                  <span className="shrink-0 text-xs text-ink-muted">{formatMs(c.duration_ms)}</span>
                )}
              </div>
              {c.arguments && Object.keys(c.arguments).length > 0 && (
                <p className="truncate font-mono text-xs text-ink-muted" title={argSummary(c.arguments)}>
                  {argSummary(c.arguments)}
                </p>
              )}
              <p className={cn("text-xs", failed ? "text-bad" : "text-ink-muted")}>
                {statusText(c)}
                {c.attempts && c.attempts > 1 ? ` after ${c.attempts} attempts` : ""}
                {failed && c.error ? `: ${c.error}` : ""}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
