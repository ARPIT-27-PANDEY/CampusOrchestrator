"use client";

import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";

/**
 * Shows `children` when the backend is open (local development) or the visitor has a session;
 * otherwise a sign-in form. The password is sent once to /api/auth/login; the session lives in an
 * HttpOnly cookie that scripts cannot read.
 */
export function AuthGate({ children, what = "this page" }: { children: ReactNode; what?: string }) {
  const session = useApi((s) => api.session(s));
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (session.loading && !session.data) return <Skeleton className="m-4 h-40 w-full max-w-md md:m-8" />;
  if (session.error) {
    return (
      <div className="p-4 md:p-8">
        <Notice tone="bad" title="Can't check your session">{session.error.message}</Notice>
      </div>
    );
  }
  if (!session.data || session.data.access_mode === "open" || session.data.authenticated) return <>{children}</>;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.login(password);
      setPassword("");
      session.reload();
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      setError(
        e?.code === "rate_limited"
          ? `Too many attempts. Try again in ${e.retryAfterS ?? 60} seconds.`
          : e?.code === "invalid_password"
            ? "That password is not correct."
            : (e?.message ?? "Sign-in failed."),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="p-4 md:p-8">
    <form onSubmit={submit} className="max-w-md space-y-4 rounded-lg border border-rule bg-panel p-5" aria-label="Sign in">
      <div className="flex items-center gap-2">
        <LockKeyhole className="size-4 text-ink-muted" aria-hidden />
        <h2 className="text-base font-semibold">Sign in to use {what}</h2>
      </div>
      <p className="text-sm text-ink-muted">
        This deployment is protected because every question uses a rate-limited language model. Ask the owner for the
        access password.
      </p>
      <label className="block text-sm">
        <span className="mb-1 block text-ink-muted">Access password</span>
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-md border border-rule bg-ground px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-ink/20"
        />
      </label>
      {error ? <p className="text-sm text-bad" role="alert">{error}</p> : null}
      <Button type="submit" disabled={pending || !password}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
    </div>
  );
}

export function SignOutButton() {
  const session = useApi((s) => api.session(s));
  if (!session.data || session.data.access_mode !== "password" || !session.data.authenticated) return null;
  return (
    <button
      type="button"
      className="text-[13px] text-ink-muted underline-offset-2 hover:text-ink hover:underline"
      onClick={async () => {
        await api.logout().catch(() => undefined);
        window.location.reload();
      }}
    >
      Sign out
    </button>
  );
}
