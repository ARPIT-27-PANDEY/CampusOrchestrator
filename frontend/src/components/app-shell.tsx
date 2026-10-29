"use client";

import { Activity, FlaskConical, LayoutGrid, MessageSquare, Signpost } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type * as React from "react";

import { SignOutButton } from "@/components/auth-gate";
import { api } from "@/lib/api";
import { SERVICES } from "@/lib/services";
import { cn, formatTime } from "@/lib/utils";
import { useApi } from "@/hooks/use-api";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/chat", label: "Ask", icon: MessageSquare },
  { href: "/sources", label: "Sources", icon: Signpost },
  { href: "/traces", label: "Traces", icon: Activity },
  { href: "/evals", label: "Evaluation", icon: FlaskConical },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const health = useApi((s) => api.health(s), { pollMs: 30000 });

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <aside className="border-rule bg-panel md:sticky md:top-0 md:h-dvh md:w-60 md:shrink-0 md:border-r">
        <div className="flex items-center justify-between gap-3 px-4 py-4 md:block md:px-5 md:py-6">
          <Link href="/" className="block">
            <span className="text-lg font-semibold tracking-tight">CampusOrchestrator</span>
            <span className="hidden text-[13px] text-ink-muted md:block">IIT Roorkee campus assistant</span>
          </Link>
        </div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm",
                  active ? "bg-ink text-panel" : "text-ink-muted hover:bg-ink/5 hover:text-ink",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="hidden px-5 pt-8 md:block">
          <p className="mb-3 text-[13px] text-ink-muted">Campus systems</p>
          <ul className="space-y-2 text-sm">
            {Object.values(SERVICES).map((s) => (
              <li key={s.id} className="flex items-center gap-2.5">
                <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
                {s.name}
              </li>
            ))}
          </ul>
        </div>

        <div className="hidden px-5 pt-8 text-[13px] text-ink-muted md:absolute md:bottom-5 md:block">
          {health.data ? (
            <>
              <p>
                Model: <span className="text-ink">{health.data.llm.model}</span>
              </p>
              <p>
                {health.data.mcp.available} of {health.data.mcp.configured} sources up, {health.data.mcp.tools} tools
              </p>
              {health.data.campus_time ? (
                <p>
                  Campus time: <span className="text-ink">{formatTime(health.data.campus_time)}</span>
                </p>
              ) : null}
              <div className="pt-2">
                <SignOutButton />
              </div>
            </>
          ) : health.error ? (
            <p className="text-bad">Backend unreachable</p>
          ) : null}
        </div>
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
