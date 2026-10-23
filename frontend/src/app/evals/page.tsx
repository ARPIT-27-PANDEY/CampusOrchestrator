"use client";

import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { EvalReport } from "@/lib/types";
import { formatMs, formatTime } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";

const METRICS: { key: string; label: string; kind: "pct" | "ms" }[] = [
  { key: "pass_rate", label: "Cases passed", kind: "pct" },
  { key: "tool_selection_accuracy", label: "Tool selection accuracy", kind: "pct" },
  { key: "answer_correctness", label: "Answer correctness", kind: "pct" },
  { key: "citation_correctness", label: "Citation correctness", kind: "pct" },
  { key: "unnecessary_tool_call_rate", label: "Unnecessary tool-call rate", kind: "pct" },
  { key: "failure_recovery_rate", label: "Recovery from simulated failures", kind: "pct" },
  { key: "latency_p50_ms", label: "End-to-end latency, median", kind: "ms" },
  { key: "latency_p95_ms", label: "End-to-end latency, 95th percentile", kind: "ms" },
  { key: "tool_duration_p50_ms", label: "Tool call duration, median", kind: "ms" },
];

function fmt(value: number | string | null | undefined, kind: "pct" | "ms"): string {
  if (value == null || typeof value === "string") return value ?? "n/a";
  return kind === "pct" ? `${(value * 100).toFixed(1)}%` : formatMs(value);
}

function Report({ report }: { report: EvalReport }) {
  return (
    <>
      <p className="mt-2 text-[13px] text-ink-muted">
        Generated {formatTime(report.generated_at)} with {report.provider} / {report.model}, {String(report.summary.cases)} cases.
      </p>
      <Notice className="mt-4" title="What these numbers measure">
        {report.note}
      </Notice>
      <table className="mt-6 w-full max-w-2xl text-sm">
        <caption className="sr-only">Evaluation metrics</caption>
        <tbody>
          {METRICS.map((m) => (
            <tr key={m.key} className="border-b border-rule">
              <th scope="row" className="py-2 pr-4 text-left font-normal text-ink-muted">
                {m.label}
              </th>
              <td className="py-2 text-right font-semibold">{fmt(report.summary[m.key], m.kind)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="mt-10 text-lg font-semibold">By category</h2>
      <ul className="mt-3 max-w-2xl space-y-2">
        {report.categories.map((c) => (
          <li key={c.category} className="grid grid-cols-[12rem_1fr_4rem] items-center gap-3 text-sm">
            <span>{c.category.replaceAll("_", " ")}</span>
            <span className="h-2 overflow-hidden rounded bg-ink/8" aria-hidden>
              <span className="block h-full bg-ok" style={{ width: `${(c.passed / c.cases) * 100}%` }} />
            </span>
            <span className="text-right text-ink-muted">
              {c.passed}/{c.cases}
            </span>
          </li>
        ))}
      </ul>

      <h2 className="mt-10 text-lg font-semibold">Cases</h2>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[44rem] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-ink-muted">
              <th className="py-2 pr-3 font-normal">Case</th>
              <th className="py-2 pr-3 font-normal">Question</th>
              <th className="py-2 pr-3 font-normal">Systems called</th>
              <th className="py-2 pr-3 font-normal">Latency</th>
              <th className="py-2 font-normal">Result</th>
            </tr>
          </thead>
          <tbody>
            {report.cases.map((c) => (
              <tr key={c.id} className="border-b border-rule align-top">
                <td className="py-2 pr-3 font-mono text-xs">{c.id}</td>
                <td className="max-w-md py-2 pr-3">{c.query}</td>
                <td className="py-2 pr-3 text-ink-muted">{c.called_servers.join(", ") || "none"}</td>
                <td className="py-2 pr-3 text-ink-muted">{formatMs(c.latency_ms)}</td>
                <td className="py-2">
                  {c.passed ? <Badge tone="ok">Passed</Badge> : <Badge tone="bad">Failed</Badge>}
                  {c.failures.map((f) => (
                    <p key={f} className="mt-1 text-xs text-bad">
                      {f}
                    </p>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function EvalsPage() {
  const report = useApi((s) => api.evals(s));
  return (
    <div className="px-4 py-6 md:px-10 md:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
      {report.loading && !report.data && <Skeleton className="mt-6 h-64 max-w-2xl" />}
      {report.error?.code === "no_eval_report" && (
        <Notice className="mt-6 max-w-2xl" title="No evaluation report yet">
          Run <code className="font-mono">python -m evals.run_eval</code> from the repository root, then reload this page.
        </Notice>
      )}
      {report.error && report.error.code !== "no_eval_report" && (
        <Notice tone="bad" className="mt-6 max-w-2xl" title="Can't load the evaluation report">
          {report.error.message}
        </Notice>
      )}
      {report.data && <Report report={report.data} />}
    </div>
  );
}
