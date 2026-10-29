"use client";

import { useState } from "react";

import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { EvalReport, EvalRunInfo, RetrievalReport, RetrievalSplit } from "@/lib/types";
import { formatMs, formatTime } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";

type Kind = "pct" | "ms" | "num";
const METRICS: { key: string; label: string; kind: Kind; definition: string; n?: string; lowerIsBetter?: boolean }[] = [
  { key: "pass_rate", label: "Cases passed", kind: "pct", definition: "Every applicable check of the case held.", n: "runs" },
  { key: "tool_selection_accuracy", label: "Tool selection (exact set)", kind: "pct", definition: "The set of tools called equals an expected set." },
  { key: "server_selection_accuracy", label: "Service selection", kind: "pct", definition: "The set of services called equals the expected set." },
  { key: "argument_accuracy", label: "Argument correctness", kind: "pct", definition: "Expected argument values (dates, filters) were passed.", n: "argument_cases" },
  { key: "answer_correctness", label: "Answer facts", kind: "pct", definition: "Required facts present and forbidden claims absent." },
  { key: "citation_correctness", label: "Citations / abstention", kind: "pct", definition: "A returned citation matches an expected document page, or the system abstained when it should.", n: "citation_cases" },
  { key: "unnecessary_tool_call_rate", label: "Unnecessary tool calls", kind: "pct", definition: "Calls to tools outside the expected set, per call.", lowerIsBetter: true },
  { key: "failure_recovery_rate", label: "Recovery from injected faults", kind: "pct", definition: "With a service failing, the healthy services still answered and the failure was reported.", n: "failure_cases" },
  { key: "latency_p50_ms", label: "Latency p50", kind: "ms", definition: "Server-side wall time of non-error runs.", n: "latency_sample", lowerIsBetter: true },
  { key: "latency_p95_ms", label: "Latency p95", kind: "ms", definition: "95th percentile of the same sample.", n: "latency_sample", lowerIsBetter: true },
  { key: "first_token_p50_ms", label: "First token p50", kind: "ms", definition: "Run start to first streamed answer token.", n: "first_token_sample", lowerIsBetter: true },
  { key: "llm_turns_mean", label: "Model turns (mean)", kind: "num", definition: "LLM calls per question.", lowerIsBetter: true },
];
const RETRIEVAL_METRICS: { key: string; label: string; kind: Kind }[] = [
  { key: "recall@5", label: "Recall@5", kind: "pct" },
  { key: "mrr", label: "MRR", kind: "num" },
  { key: "ndcg@5", label: "nDCG@5", kind: "num" },
  { key: "abstain_recall", label: "Abstains when unanswerable", kind: "pct" },
  { key: "false_abstention_rate", label: "False abstention", kind: "pct" },
  { key: "search_p50_ms", label: "Search p50", kind: "ms" },
];

function fmt(value: unknown, kind: Kind): string {
  if (value == null) return "n/a";
  if (typeof value !== "number") return String(value);
  if (kind === "pct") return `${(value * 100).toFixed(1)}%`;
  if (kind === "ms") return formatMs(value);
  return value.toFixed(2);
}

function isMock(r: { provider?: string | null }) {
  return r.provider === "mock";
}

function Delta({ a, b, kind, lowerIsBetter }: { a: unknown; b: unknown; kind: Kind; lowerIsBetter?: boolean }) {
  if (typeof a !== "number" || typeof b !== "number") return <span className="text-ink-muted">–</span>;
  const d = b - a;
  if (Math.abs(d) < 1e-9) return <span className="text-ink-muted">same</span>;
  const better = lowerIsBetter ? d < 0 : d > 0;
  const text = kind === "pct" ? `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)} pts` : `${d > 0 ? "+" : ""}${kind === "ms" ? formatMs(Math.abs(d)) : d.toFixed(2)}`;
  return <span className={better ? "text-ok" : "text-bad"}>{kind === "ms" && d < 0 ? `-${text.replace(/^\+/, "")}` : text}</span>;
}

function RunMeta({ report }: { report: EvalReport }) {
  const c = report.config ?? {};
  return (
    <p className="mt-2 text-[13px] text-ink-muted">
      <span className="font-mono">{report.run_id ?? "legacy report"}</span>, {formatTime(report.generated_at)}.{" "}
      {report.dataset ?? "dataset"} v{String(c.dataset_version ?? 1)}, {report.provider} / {report.model},{" "}
      {report.transport ?? "inprocess"} transport, retriever {String(c.retriever ?? "hashing")}
      {c.repeat && Number(c.repeat) > 1 ? `, ${String(c.repeat)} repeats` : ""}.
    </p>
  );
}

function AgentReport({ report, compare }: { report: EvalReport; compare: EvalReport | null }) {
  const s = report.summary;
  const regress =
    compare &&
    report.cases.filter((c) => !c.passed && compare.cases.some((o) => o.id === c.id && o.passed)).map((c) => c.id);
  const improve =
    compare &&
    report.cases.filter((c) => c.passed && compare.cases.some((o) => o.id === c.id && !o.passed)).map((c) => c.id);
  return (
    <>
      <RunMeta report={report} />
      <Notice className="mt-4 max-w-3xl" tone={isMock(report) ? "warn" : "info"} title="What these numbers measure">
        {report.note}
      </Notice>
      {compare && compare.dataset !== report.dataset ? (
        <Notice className="mt-3 max-w-3xl" tone="warn" title="Different datasets">
          The two runs used different scenario sets, so their numbers are not comparable.
        </Notice>
      ) : null}
      {compare && isMock(compare) !== isMock(report) ? (
        <Notice className="mt-3 max-w-3xl" tone="warn" title="Mock and live runs">
          One run uses the deterministic keyword router, the other a real model: tool selection is not measuring the same thing.
        </Notice>
      ) : null}
      <div className="mt-6 overflow-x-auto">
        <table className="w-full max-w-4xl min-w-[36rem] text-sm">
          <caption className="sr-only">Agent evaluation metrics</caption>
          <thead>
            <tr className="border-b border-rule text-left text-ink-muted">
              <th className="py-2 pr-3 font-normal">Metric</th>
              <th className="py-2 pr-3 text-right font-normal">This run</th>
              {compare ? <th className="py-2 pr-3 text-right font-normal">Compared run</th> : null}
              {compare ? <th className="py-2 text-right font-normal">Change</th> : null}
            </tr>
          </thead>
          <tbody>
            {METRICS.map((m) => (
              <tr key={m.key} className="border-b border-rule align-top">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  {m.label}
                  <span className="block text-xs text-ink-muted">
                    {m.definition}
                    {m.n && s[m.n] != null ? ` n = ${String(s[m.n])}.` : ""}
                  </span>
                </th>
                <td className="py-2 pr-3 text-right font-semibold">{fmt(s[m.key], m.kind)}</td>
                {compare ? <td className="py-2 pr-3 text-right">{fmt(compare.summary[m.key], m.kind)}</td> : null}
                {compare ? (
                  <td className="py-2 text-right text-xs">
                    <Delta a={compare.summary[m.key]} b={s[m.key]} kind={m.kind} lowerIsBetter={m.lowerIsBetter} />
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {report.latency_note ? <p className="mt-2 max-w-3xl text-xs text-ink-muted">{report.latency_note}</p> : null}
      {compare ? (
        <p className="mt-4 text-sm">
          <span className="text-bad">Regressions:</span> {regress?.join(", ") || "none"}.{" "}
          <span className="text-ok">Improvements:</span> {improve?.join(", ") || "none"}.
        </p>
      ) : null}

      <h3 className="mt-8 font-semibold">By category</h3>
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

      <details className="mt-8">
        <summary className="cursor-pointer font-semibold">Cases ({report.cases.length})</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-ink-muted">
                <th className="py-2 pr-3 font-normal">Case</th>
                <th className="py-2 pr-3 font-normal">Question</th>
                <th className="py-2 pr-3 font-normal">Tools called</th>
                <th className="py-2 pr-3 font-normal">Latency</th>
                <th className="py-2 font-normal">Result</th>
              </tr>
            </thead>
            <tbody>
              {report.cases.map((c) => (
                <tr key={`${c.id}-${c.repeat ?? 1}`} className="border-b border-rule align-top">
                  <td className="py-2 pr-3 font-mono text-xs">
                    {c.id}
                    {c.repeat && c.repeat > 1 ? ` #${c.repeat}` : ""}
                  </td>
                  <td className="max-w-md py-2 pr-3">{c.query}</td>
                  <td className="py-2 pr-3 text-xs text-ink-muted">
                    {(c.called_tools ?? c.called_servers).join(", ") || "none"}
                  </td>
                  <td className="py-2 pr-3 text-ink-muted">{formatMs(c.latency_ms)}</td>
                  <td className="py-2">
                    {c.passed ? <Badge tone="ok">Passed</Badge> : <Badge tone="bad">Failed</Badge>}
                    {c.failure_class ? <span className="ml-2 text-xs text-ink-muted">{c.failure_class.replace("_", " ")}</span> : null}
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
      </details>
    </>
  );
}

function RetrievalTable({ report }: { report: RetrievalReport }) {
  const test = (r: RetrievalReport["results"][number]): RetrievalSplit | undefined => r.splits?.test;
  const sample = report.results.find((r) => r.splits)?.splits?.test;
  return (
    <>
      <p className="mt-2 text-[13px] text-ink-muted">
        <span className="font-mono">{report.run_id}</span>, {formatTime(report.generated_at)}. Test split
        {sample ? ` (${sample.queries} questions, ${sample.no_answer} without a supporting document)` : ""}; thresholds{" "}
        {report.tuned ? "chosen on the dev split only" : "as configured"}.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full max-w-4xl min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-ink-muted">
              <th className="py-2 pr-3 font-normal">Retriever</th>
              {RETRIEVAL_METRICS.map((m) => (
                <th key={m.key} className="py-2 pr-3 text-right font-normal">
                  {m.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.results.map((r) => (
              <tr key={r.retriever} className="border-b border-rule">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  {r.retriever}
                  <span className="block text-xs text-ink-muted">{r.embedding_model ?? r.reason}</span>
                </th>
                {r.status === "ok"
                  ? RETRIEVAL_METRICS.map((m) => (
                      <td key={m.key} className="py-2 pr-3 text-right">
                        {fmt(test(r)?.[m.key], m.kind)}
                      </td>
                    ))
                  : RETRIEVAL_METRICS.map((m) => (
                      <td key={m.key} className="py-2 pr-3 text-right text-ink-muted">
                        not run
                      </td>
                    ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 max-w-3xl text-xs text-ink-muted">
        Recall@5: share of labelled passages in the top five. MRR: reciprocal rank of the first relevant passage.
        nDCG@5 uses graded labels. A retriever that is not installed is shown as not run, never copied from another.
      </p>
    </>
  );
}

function pickDefault(runs: EvalRunInfo[]): string | undefined {
  const agent = runs.filter((r) => r.kind === "agent");
  return (
    agent.find((r) => r.dataset === "campus_eval_v2.yaml" && r.provider === "mock" && (r.repeat ?? 1) === 1 && (r.retriever ?? "hashing") === "hashing")
      ?.run_id ?? agent[0]?.run_id
  );
}

function runLabel(r: EvalRunInfo) {
  const when = r.generated_at ? formatTime(r.generated_at) : "";
  const pass = r.pass_rate != null ? `${(r.pass_rate * 100).toFixed(0)}%` : "";
  return `${r.legacy ? "legacy " : ""}${r.dataset ?? ""} · ${r.provider ?? ""}${r.retriever && r.retriever !== "hashing" ? ` · ${r.retriever}` : ""}${(r.repeat ?? 1) > 1 ? ` · x${r.repeat}` : ""} · ${pass} · ${when}`;
}

export default function EvalsPage() {
  const runs = useApi((s) => api.evalRuns(s));
  const [chosen, setChosen] = useState<string>("");
  const [compareId, setCompareId] = useState<string>("");
  const agentRuns = (runs.data ?? []).filter((r) => r.kind === "agent");
  const live = agentRuns.filter((r) => !isMock(r));
  const selectedId = chosen || pickDefault(runs.data ?? []) || "";
  const retrievalId = (runs.data ?? []).find((r) => r.kind === "retrieval")?.run_id ?? "";
  const selected = useApi((s) => (selectedId ? api.evalRun<EvalReport>(selectedId, s) : Promise.resolve(null)), { key: selectedId });
  const compared = useApi((s) => (compareId ? api.evalRun<EvalReport>(compareId, s) : Promise.resolve(null)), { key: compareId });
  const retrieval = useApi((s) => (retrievalId ? api.evalRun<RetrievalReport>(retrievalId, s) : Promise.resolve(null)), { key: retrievalId });
  const report = selected.data;
  const faultCats = report?.categories.filter((c) => ["failure", "llm_failure", "tool_budget"].includes(c.category)) ?? [];
  const ext = report?.cases.filter((c) => c.category === "extensibility") ?? [];

  return (
    <div className="px-4 py-6 md:px-10 md:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
      <p className="mt-2 max-w-3xl text-sm text-ink-muted">
        Every number here is produced by <code className="font-mono">evals/run_eval.py</code> or{" "}
        <code className="font-mono">evals/run_retrieval.py</code> and stored as an immutable run; nothing is entered by hand.
      </p>
      {runs.loading && !runs.data && <Skeleton className="mt-6 h-64 max-w-2xl" />}
      {runs.error && (
        <Notice tone="bad" className="mt-6 max-w-2xl" title="Can't load evaluation runs">
          {runs.error.message}
        </Notice>
      )}
      {runs.data && runs.data.length === 0 && (
        <Notice className="mt-6 max-w-2xl" title="No evaluation runs yet">
          Run <code className="font-mono">python -m evals.run_eval</code> from the repository root, then reload this page.
        </Notice>
      )}

      {runs.data && runs.data.length > 0 && (
        <>
          <section className="mt-8">
            <h2 className="text-lg font-semibold">1. Does the real model choose the right services and tools?</h2>
            {live.length === 0 ? (
              <Notice className="mt-3 max-w-3xl" tone="warn" title="No live-model run is saved">
                The runs below use MockProvider, a deterministic keyword router. Their tool-selection numbers test the
                pipeline, not GPT-OSS-120B. A live run is opt-in because it uses Groq quota:{" "}
                <code className="font-mono">python -m evals.run_eval --provider groq --yes-live</code>.
              </Notice>
            ) : (
              <p className="mt-2 text-sm text-ink-muted">
                {live.length} live-model run(s) saved; pick one below. Sample sizes are shown per metric.
              </p>
            )}
            <div className="mt-4 flex flex-wrap items-end gap-4 text-sm">
              <label>
                <span className="mb-1 block text-ink-muted">Run</span>
                <select
                  className="max-w-full rounded-md border border-rule bg-panel px-2 py-1.5"
                  value={selectedId}
                  onChange={(e) => setChosen(e.target.value)}
                >
                  {agentRuns.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {runLabel(r)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-ink-muted">Compare with</span>
                <select
                  className="max-w-full rounded-md border border-rule bg-panel px-2 py-1.5"
                  value={compareId}
                  onChange={(e) => setCompareId(e.target.value)}
                >
                  <option value="">(no comparison)</option>
                  {agentRuns
                    .filter((r) => r.run_id !== selectedId)
                    .map((r) => (
                      <option key={r.run_id} value={r.run_id}>
                        {runLabel(r)}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            {selected.loading && !report ? <Skeleton className="mt-6 h-64 max-w-2xl" /> : null}
            {report ? <AgentReport report={report} compare={compareId ? compared.data : null} /> : null}
          </section>

          <section className="mt-12">
            <h2 className="text-lg font-semibold">2-3. Does semantic, then hybrid, retrieval beat hashing?</h2>
            {retrieval.data ? (
              <RetrievalTable report={retrieval.data} />
            ) : (
              <p className="mt-2 text-sm text-ink-muted">
                No retrieval benchmark saved. Run <code className="font-mono">python -m evals.run_retrieval --tune</code>.
              </p>
            )}
          </section>

          <section className="mt-12">
            <h2 className="text-lg font-semibold">4. Does it stay useful when a service fails?</h2>
            {faultCats.length ? (
              <ul className="mt-3 max-w-2xl space-y-1 text-sm">
                {faultCats.map((c) => (
                  <li key={c.category}>
                    {c.category.replaceAll("_", " ")}: <span className="font-semibold">{c.passed}/{c.cases}</span> scenarios
                    handled (healthy services still answered, the failed one was named, nothing was invented).
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-ink-muted">The selected run has no fault-injection scenarios.</p>
            )}
          </section>

          <section className="mt-12 mb-8">
            <h2 className="text-lg font-semibold">5. Does a new server integrate without orchestrator changes?</h2>
            <p className="mt-2 max-w-3xl text-sm text-ink-muted">
              A test-only Transport server is started over real HTTP, registered by configuration, discovered and called
              (<code className="font-mono">tests/test_extensibility.py</code>, which also checks that no backend file
              names it).
              {ext.length ? ` In the selected run: ${ext.filter((c) => c.passed).length}/${ext.length} dynamic-discovery case(s) passed.` : ""}
            </p>
          </section>
        </>
      )}
    </div>
  );
}
