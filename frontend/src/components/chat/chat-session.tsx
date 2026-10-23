"use client";

import { SendHorizontal, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useChat } from "@/hooks/use-chat";
import { SERVICES } from "@/lib/services";

import { Button } from "@/components/ui/button";

import { TurnView } from "./answer";

export const EXAMPLES = [
  "Find the next AI workshop, check whether Introduction to Algorithms is available in the library, and tell me which prerequisite the handbook specifies.",
  "What is the minimum attendance requirement?",
  "How much is the masala dosa?",
  "Are there any hackathons coming up?",
  "What are the library hours on Sunday?",
];

export function ChatSession({ initialQuery }: { initialQuery?: string }) {
  const { turns, busy, send, stop } = useChat();
  const [draft, setDraft] = useState("");
  const [outage, setOutage] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (initialQuery && !started.current) {
      started.current = true;
      void send(initialQuery);
    }
  }, [initialQuery, send]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length]);

  const submit = (text = draft) => {
    if (!text.trim()) return;
    void send(text, outage ? { [outage]: "down" } : undefined);
    setDraft("");
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="flex-1 space-y-8 px-4 py-6 md:px-10 md:py-10">
        {turns.length === 0 ? (
          <div className="max-w-[72ch]">
            <h1 className="text-2xl font-semibold tracking-tight">Ask the campus</h1>
            <p className="mt-2 text-ink-muted">
              One question can reach the library, events calendar, cafeteria and academic handbook. Each answer shows
              the route it took and the evidence it used.
            </p>
            <ul className="mt-6 space-y-2">
              {EXAMPLES.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => submit(q)}
                    className="w-full rounded-md border border-rule bg-panel px-3 py-2 text-left text-sm hover:border-ink/40"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          turns.map((t) => <TurnView key={t.id} turn={t} />)
        )}
        <div ref={endRef} />
      </div>

      <form
        className="sticky bottom-0 z-20 border-t border-rule bg-ground/95 px-4 py-3 backdrop-blur md:px-10"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="flex items-end gap-2">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={2}
            maxLength={2000}
            placeholder="Ask about books, events, the menu or academic policy"
            className="min-h-12 flex-1 resize-none rounded-md border border-rule bg-panel px-3 py-2 text-[15px] placeholder:text-ink-muted"
          />
          {busy ? (
            <Button type="button" variant="outline" onClick={stop} aria-label="Stop answering">
              <Square /> Stop
            </Button>
          ) : (
            <Button type="submit" disabled={!draft.trim()}>
              <SendHorizontal /> Ask
            </Button>
          )}
        </div>
        <details className="mt-2 text-[13px] text-ink-muted">
          <summary className="cursor-pointer">Failure testing</summary>
          <label className="mt-2 flex items-center gap-2">
            Treat this system as down for the next question:
            <select
              value={outage}
              onChange={(e) => setOutage(e.target.value)}
              className="rounded border border-rule bg-panel px-2 py-1 text-ink"
            >
              <option value="">None</option>
              {Object.values(SERVICES).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1">Requires the backend to run with ALLOW_FAULT_INJECTION=true.</p>
        </details>
      </form>
    </div>
  );
}
