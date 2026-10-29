"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";

import type { Turn } from "@/lib/chat-state";
import { serviceMeta } from "@/lib/services";
import type { ToolCallSummary } from "@/lib/types";
import { formatMs } from "@/lib/utils";

import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";

import { CitationList } from "./citations";
import { SourceTags } from "./source-tags";
import { ToolRoute } from "./tool-route";

const FAILURE_TITLE: Record<string, string> = {
  auth_required: "Please sign in again",
  rate_limited: "Too many questions in a short time",
  too_many_requests: "The assistant is busy",
  backend_unreachable: "Can't reach the assistant",
};

const FAILURE_TEXT: Record<string, string> = {
  timeout: "did not respond in time",
  unavailable: "is unreachable",
  protocol_error: "returned an invalid response",
  malformed_response: "returned malformed data",
  tool_error: "reported an error",
};

/** One line per failed tool call, e.g. "Events: did not respond in time". */
export function failedCalls(calls: ToolCallSummary[]): string[] {
  const lines = calls
    .filter((c) => c.status in FAILURE_TEXT)
    .map((c) => `${serviceMeta(c.server_id ?? "").name}: ${FAILURE_TEXT[c.status]}`);
  return [...new Set(lines)];
}

const PHASE_TEXT: Record<Turn["phase"], string> = {
  connecting: "Connecting…",
  discovering: "Discovering campus tools…",
  thinking: "Deciding which systems to ask…",
  calling: "Asking campus systems…",
  answering: "Writing the answer…",
  done: "",
  failed: "",
};

export function TurnView({ turn }: { turn: Turn }) {
  const r = turn.result;
  const finished = turn.phase === "done" || turn.phase === "failed";
  return (
    <article className="border-b border-rule pb-8" aria-busy={!finished}>
      <p className="mb-4 max-w-[72ch] text-[17px] font-semibold leading-snug">{turn.query}</p>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0 space-y-4">
          {turn.draft ? (
            <div className="answer-prose max-w-[72ch] text-[15px] leading-relaxed">
              <ReactMarkdown>{turn.draft}</ReactMarkdown>
            </div>
          ) : !finished ? (
            <div className="space-y-2" aria-label="Loading answer">
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-9/12" />
              <Skeleton className="h-4 w-10/12" />
            </div>
          ) : null}

          {!finished && <p className="text-[13px] text-ink-muted" aria-live="polite">{PHASE_TEXT[turn.phase]}</p>}

          {turn.phase === "failed" && !r && (
            <Notice tone="bad" title={FAILURE_TITLE[turn.error?.code ?? ""] ?? "The answer didn't arrive"}>
              {turn.error?.code === "auth_required"
                ? "Your session has expired. Reload the page and sign in again."
                : (turn.error?.message ?? "The connection closed before the backend finished. Try asking again.")}
            </Notice>
          )}

          {r && (
            <>
              {r.status === "partial" && (
                <Notice tone="warn" title="Partial answer: some systems could not be checked">
                  <ul className="mt-1 list-disc pl-4">
                    {failedCalls(r.tool_calls).map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                  <p className="mt-1">Anything from those systems is missing from the answer; it was not treated as &quot;no results&quot;.</p>
                </Notice>
              )}
              {r.status === "error" && (
                <Notice tone="bad" title="The assistant couldn't finish">
                  {turn.error?.message ?? r.warnings[0] ?? r.error_code}
                </Notice>
              )}
              {r.insufficient_evidence && (
                <Notice title="No supporting passage found">
                  The indexed handbooks don&apos;t contain evidence for this question, so no policy is quoted.
                </Notice>
              )}
              {r.citation_check.unsupported.length > 0 && (
                <Notice tone="warn" title="Unverified page reference">
                  These references don&apos;t match any retrieved passage: {r.citation_check.unsupported.join(", ")}
                </Notice>
              )}
              {(r.citation_check.unsupported_numbers?.length ?? 0) > 0 && (
                <Notice tone="warn" title="Number not found in the cited passage">
                  {r.citation_check.unsupported_numbers?.join(", ")} appear next to a citation but not in the cited text.
                  Check the excerpt before relying on them.
                </Notice>
              )}
              <SourceTags sources={r.sources} />
              <CitationList citations={r.citations} />
            </>
          )}
        </div>

        <aside className="rounded-md border border-rule bg-panel p-4 lg:self-start" aria-label="Route through campus systems">
          <h3 className="mb-3 text-sm font-medium">Route</h3>
          <ToolRoute calls={turn.toolCalls} finished={finished} />
          {r && (
            <div className="mt-4 space-y-0.5 border-t border-rule pt-3 text-xs text-ink-muted">
              <p>
                {formatMs(r.latency_ms)} total, {r.iterations} model {r.iterations === 1 ? "turn" : "turns"}
              </p>
              <p>{r.model}</p>
              <Link href={`/traces?id=${r.trace_id}`} className="text-focus underline-offset-2 hover:underline">
                Open trace
              </Link>
            </div>
          )}
        </aside>
      </div>
    </article>
  );
}
