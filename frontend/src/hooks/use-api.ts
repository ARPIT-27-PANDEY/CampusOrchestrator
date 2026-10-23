"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

import { ApiError } from "@/lib/api";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Minimal client-side fetch hook with abort-on-unmount and optional polling.
 * `loading` is derived (the latest request id has not settled yet) so no state is set synchronously in the effect.
 * The latest `fetcher` is always used; change `key` to force a refetch when its inputs change.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  { pollMs, key }: { pollMs?: number; key?: string } = {},
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [requested, setRequested] = useState(0);
  const [settled, setSettled] = useState(-1);

  const run = useEffectEvent((signal: AbortSignal) => fetcher(signal));

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSettled(requested);
      });
    const timer = pollMs ? setTimeout(() => setRequested((n) => n + 1), pollMs) : undefined;
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [requested, pollMs, key]);

  const reload = useCallback(() => setRequested((n) => n + 1), []);
  return { data, error, loading: settled !== requested, reload };
}
