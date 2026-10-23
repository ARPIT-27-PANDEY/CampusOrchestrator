"use client";

import type { AgentTrace, TraceStep } from "@/lib/types";
import { serviceMeta } from "@/lib/services";
import { formatMs, formatTime, splitTool } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";

function StepRow({ step }: { step: TraceStep }) {
  const d = step.detail as Record<string, unknown>;
  if (step.kind === "discovery") {
    const servers = (d.servers ?? {}) as Record<string, string>;
    return (
      <>
        <p className="font-medium">Tool discovery</p>
        <p className="text-ink-muted">
          {(d.tools as string[] | undefined)?.length ?? 0} tools from{" "}
          {Object.entries(servers)
            .map(([id, st]) => `${serviceMeta(id).name} (${st.replace("_", " ")})`)
            .join(", ")}
        </p>
      </>
    );
  }
  if (step.kind === "llm") {
    const usage = (d.usage ?? {}) as Record<string, number>;
    const requested = (d.requested_tools as string[] | undefined) ?? [];
    return (
      <>
        <p className="font-medium">Model turn {String(d.iteration)}</p>
        <p className="text-ink-muted">
          {d.error
            ? `Failed: ${String(d.message ?? d.error)}`
            : requested.length
              ? `Requested ${requested.map((t) => splitTool(t).tool).join(", ")}`
              : `Wrote the answer (${String(d.content_chars ?? 0)} characters)`}
          {usage.total_tokens ? `, ${usage.total_tokens} tokens` : ""}
        </p>
      </>
    );
  }
  const svc = serviceMeta(d.server_id as string | null);
  return (
    <>
      <p className="font-medium">
        <span style={{ color: svc.color }}>{svc.name}</span> {splitTool(String(d.tool)).tool}{" "}
        <Badge tone={d.status === "success" ? "ok" : "bad"}>{String(d.status).replace("_", " ")}</Badge>
        {d.cached ? <Badge className="ml-1">reused</Badge> : null}
      </p>
      <p className="font-mono text-xs text-ink-muted">{JSON.stringify(d.arguments)}</p>
      {typeof d.error === "string" && <p className="text-bad">{d.error}</p>}
      {typeof d.result_preview === "string" && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-ink-muted">Result returned to the model</summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded bg-ground p-2 font-mono text-xs whitespace-pre-wrap">
            {d.result_preview}
          </pre>
        </details>
      )}
    </>
  );
}

export function TraceDetail({ trace }: { trace: AgentTrace }) {
  const r = trace.result;
  return (
    <div>
      <h2 className="text-lg font-semibold leading-snug">{trace.query}</h2>
      <p className="mt-1 text-[13px] text-ink-muted">
        {formatTime(trace.created_at)}, {formatMs(trace.latency_ms)}, {trace.provider} / {trace.model}, status {trace.status}
      </p>
      <ol className="mt-5 space-y-3">
        {trace.steps.map((step, i) => (
          <li key={i} className="grid grid-cols-[4.5rem_1fr] gap-3 border-t border-rule pt-3 text-sm">
            <span className="text-xs text-ink-muted">
              {formatMs(step.kind === "tool" ? Number(step.detail.tool_duration_ms ?? step.duration_ms) : step.duration_ms)}
            </span>
            <div className="min-w-0">
              <StepRow step={step} />
            </div>
          </li>
        ))}
      </ol>
      {r && (
        <div className="mt-6 border-t border-rule pt-4 text-sm">
          <h3 className="mb-1 font-medium">Final answer</h3>
          <p className="max-w-[72ch] whitespace-pre-wrap text-ink">{r.answer}</p>
          {r.warnings.length > 0 && <p className="mt-2 text-warn">{r.warnings.join(" ")}</p>}
        </div>
      )}
    </div>
  );
}
