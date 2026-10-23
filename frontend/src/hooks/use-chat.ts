"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, streamChat } from "@/lib/api";
import { applyEvent, newTurn, type Turn } from "@/lib/chat-state";

export function useChat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const update = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((all) => all.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const send = useCallback(
    async (query: string, simulateFailures?: Record<string, "down" | "timeout">) => {
      const text = query.trim();
      if (!text || busy) return;
      const id = crypto.randomUUID();
      setTurns((all) => [...all, newTurn(id, text)]);
      setBusy(true);
      const ctrl = new AbortController();
      controller.current = ctrl;
      try {
        for await (const ev of streamChat(text, { simulateFailures, signal: ctrl.signal })) {
          update(id, (t) => applyEvent(t, ev.event, ev.data));
        }
        update(id, (t) => (t.result ? t : { ...t, phase: "failed" }));
      } catch (err) {
        const aborted = (err as Error).name === "AbortError";
        const e =
          err instanceof ApiError
            ? { code: err.code, message: err.message }
            : { code: aborted ? "cancelled" : "stream_error", message: aborted ? "Stopped." : "The response stream broke off." };
        update(id, (t) => ({ ...t, phase: "failed", error: e }));
      } finally {
        setBusy(false);
        controller.current = null;
      }
    },
    [busy, update],
  );

  const stop = useCallback(() => controller.current?.abort(), []);
  return { turns, busy, send, stop };
}
