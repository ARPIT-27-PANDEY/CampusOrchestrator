"use client";

import { SendHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { formatMs } from "@/lib/utils";

import { EXAMPLES } from "@/components/chat/chat-session";
import { SourceBoard } from "@/components/sources/source-board";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";

export default function OverviewPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const sources = useApi((s) => api.sources(false, s), { pollMs: 30000 });
  const traces = useApi((s) => api.traces(s), { pollMs: 15000 });
  const ask = (text: string) => text.trim() && router.push(`/chat?q=${encodeURIComponent(text.trim())}`);

  return (
    <div className="px-4 py-8 md:px-10 md:py-14">
      <section className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">One question, every campus system.</h1>
        <p className="mt-3 max-w-[64ch] text-ink-muted">
          CampusOS AI discovers the tools each campus system publishes over the Model Context Protocol, asks only the
          ones your question needs, and shows the evidence behind every answer.
        </p>
        <form
          className="mt-6 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            ask(q);
          }}
        >
          <label htmlFor="overview-q" className="sr-only">
            Your question
          </label>
          <input
            id="overview-q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Is Deep Learning on the shelf, and what's for lunch?"
            className="h-11 min-w-0 flex-1 rounded-md border border-rule bg-panel px-3 text-[15px] placeholder:text-ink-muted"
          />
          <Button type="submit" className="h-11" disabled={!q.trim()}>
            <SendHorizontal /> Ask
          </Button>
        </form>
        <button
          type="button"
          onClick={() => ask(EXAMPLES[0])}
          className="mt-3 text-left text-sm text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
        >
          Try: {EXAMPLES[0]}
        </button>
      </section>

      <section className="mt-12" aria-labelledby="sources-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="sources-h" className="text-lg font-semibold">
            Campus systems
          </h2>
          <Link href="/sources" className="text-sm text-focus hover:underline">
            Source details
          </Link>
        </div>
        {sources.error ? (
          <Notice tone="bad" title="Can't reach the backend">
            {sources.error.message} Start it with <code className="font-mono">make dev</code> or Docker Compose.
          </Notice>
        ) : (
          <SourceBoard servers={sources.data?.servers} loading={sources.loading} />
        )}
      </section>

      <section className="mt-12 max-w-3xl" aria-labelledby="recent-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="recent-h" className="text-lg font-semibold">
            Recent questions
          </h2>
          <Link href="/traces" className="text-sm text-focus hover:underline">
            All traces
          </Link>
        </div>
        {traces.data && traces.data.length === 0 && (
          <p className="text-sm text-ink-muted">Nothing asked yet since the backend started.</p>
        )}
        <ul className="divide-y divide-rule">
          {traces.data?.slice(0, 5).map((t) => (
            <li key={t.trace_id}>
              <Link href={`/traces?id=${t.trace_id}`} className="flex items-baseline justify-between gap-4 py-2.5 text-sm hover:text-focus">
                <span className="line-clamp-1">{t.query}</span>
                <span className="shrink-0 text-xs text-ink-muted">
                  {t.tool_calls} calls, {formatMs(t.latency_ms)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
