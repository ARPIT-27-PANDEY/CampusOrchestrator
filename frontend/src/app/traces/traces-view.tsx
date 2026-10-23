"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { cn, formatMs, formatTime } from "@/lib/utils";

import { TraceDetail } from "@/components/traces/trace-detail";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";

export function TracesView() {
  const selected = useSearchParams().get("id");
  const list = useApi((s) => api.traces(s), { pollMs: 10000 });
  const detail = useApi((s) => (selected ? api.trace(selected, s) : Promise.resolve(null)), { key: selected ?? "" });
  const active = selected;

  return (
    <div className="px-4 py-6 md:px-10 md:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Execution traces</h1>
      <p className="mt-2 max-w-[72ch] text-ink-muted">
        Every question records tool discovery, each model turn, and each MCP call with its arguments, status and timing.
        Traces are kept in the backend&apos;s memory, so they reset when it restarts.
      </p>
      {list.error && <Notice tone="bad" title="Can't load traces" className="mt-4">{list.error.message}</Notice>}
      <div className="mt-6 grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <ul className="space-y-1" aria-label="Recent questions">
          {!list.data && !list.error && [0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}
          {list.data?.length === 0 && (
            <li className="text-sm text-ink-muted">
              No traces yet. <Link href="/chat" className="text-focus underline">Ask a question</Link> to create one.
            </li>
          )}
          {list.data?.map((t) => (
            <li key={t.trace_id}>
              <Link
                href={`/traces?id=${t.trace_id}`}
                aria-current={t.trace_id === active ? "true" : undefined}
                className={cn(
                  "block rounded-md border px-3 py-2 text-sm",
                  t.trace_id === active ? "border-ink bg-panel" : "border-transparent hover:bg-panel",
                )}
              >
                <span className="line-clamp-2">{t.query}</span>
                <span className="mt-0.5 block text-xs text-ink-muted">
                  {formatTime(t.created_at)}, {t.tool_calls} tool calls, {formatMs(t.latency_ms)},{" "}
                  <span className={t.status === "ok" ? "text-ok" : t.status === "partial" ? "text-warn" : "text-bad"}>{t.status}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
        <section className="min-w-0 rounded-md border border-rule bg-panel p-5" aria-label="Trace detail">
          {selected ? (
            detail.data ? (
              <TraceDetail trace={detail.data} />
            ) : detail.error ? (
              <Notice tone="bad" title="Trace not found">{detail.error.message}</Notice>
            ) : (
              <Skeleton className="h-40" />
            )
          ) : (
            <p className="text-sm text-ink-muted">Select a question to see its full trace.</p>
          )}
        </section>
      </div>
    </div>
  );
}
