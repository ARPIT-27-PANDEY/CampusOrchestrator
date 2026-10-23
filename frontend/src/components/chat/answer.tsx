"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";

import type { Turn } from "@/lib/chat-state";
import { formatMs } from "@/lib/utils";

import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";

import { CitationList } from "./citations";
import { SourceTags } from "./source-tags";
import { ToolRoute } from "./tool-route";

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
            <Notice tone="bad" title="The answer didn't arrive">
              {turn.error?.message ?? "The connection closed before the backend finished. Try asking again."}
            </Notice>
          )}

          {r && (
            <>
              {r.status === "partial" && (
                <Notice tone="warn" title="Partial answer">
                  Some systems didn&apos;t respond, so parts of this answer are missing. {r.warnings.join(" ")}
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
