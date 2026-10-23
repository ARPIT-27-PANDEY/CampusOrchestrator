"use client";

import { RefreshCw } from "lucide-react";

import type { ServerState } from "@/lib/types";
import { serviceMeta } from "@/lib/services";
import { cn, formatMs, formatTime } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS: Record<ServerState["status"], { text: string; tone: "ok" | "bad" | "neutral" | "warn" }> = {
  available: { text: "Available", tone: "ok" },
  unavailable: { text: "Unavailable", tone: "bad" },
  not_configured: { text: "Not configured", tone: "neutral" },
  unknown: { text: "Not checked yet", tone: "neutral" },
};

const MODE_TEXT: Record<string, string> = { demo: "Demo data", imported: "Imported file", live: "Live source" };

/** Wayfinding-style sign for one campus system: its colour band, live status and data provenance. */
export function SourceSign({ server, detailed = false }: { server: ServerState; detailed?: boolean }) {
  const svc = serviceMeta(server.id);
  const Icon = svc.icon;
  const status = STATUS[server.status];
  const docs = (server.source_detail?.documents as { title: string; pages: number; ingested_at: string; document_version: string }[] | undefined) ?? [];
  return (
    <section
      aria-label={`${svc.name} source`}
      className={cn("flex flex-col overflow-hidden rounded-md border border-rule bg-panel", server.data_mode === "demo" && "demo-hatch")}
    >
      <div className="flex items-center gap-3 px-4 py-3 text-white" style={{ background: svc.color }}>
        <Icon className="size-5" aria-hidden />
        <h2 className="text-base font-semibold">{svc.name}</h2>
      </div>
      <div className="flex-1 space-y-2 bg-panel/90 px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={status.tone}>{status.text}</Badge>
          {server.data_mode && <Badge tone={server.data_mode === "live" ? "ok" : "demo"}>{MODE_TEXT[server.data_mode] ?? server.data_mode}</Badge>}
        </div>
        {server.status === "available" && (
          <p className="text-ink-muted">
            {server.tool_names.length} tools discovered in {formatMs(server.latency_ms)}
          </p>
        )}
        {server.error && <p className="text-bad">{server.error}</p>}
        {server.status === "not_configured" && <p className="text-ink-muted">No URL is configured for this system.</p>}
        {detailed && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 pt-1 text-[13px]">
            <dt className="text-ink-muted">Endpoint</dt>
            <dd className="truncate font-mono text-xs">{server.url ?? "none"}</dd>
            <dt className="text-ink-muted">Protocol</dt>
            <dd>{server.protocol_version ?? "unknown"}</dd>
            <dt className="text-ink-muted">Checked</dt>
            <dd>{formatTime(server.last_checked)}</dd>
            {server.tool_names.length > 0 && (
              <>
                <dt className="text-ink-muted">Tools</dt>
                <dd className="font-mono text-xs">{server.tool_names.join(", ")}</dd>
              </>
            )}
            {typeof server.source_detail?.data_as_of === "string" && (
              <>
                <dt className="text-ink-muted">Data as of</dt>
                <dd>{server.source_detail.data_as_of}</dd>
              </>
            )}
            {docs.length > 0 && (
              <>
                <dt className="text-ink-muted">Indexed</dt>
                <dd>
                  {docs.map((d) => (
                    <span key={d.document_version} className="block">
                      {d.title} ({d.pages} pages, ingested {formatTime(d.ingested_at)})
                    </span>
                  ))}
                </dd>
              </>
            )}
          </dl>
        )}
      </div>
    </section>
  );
}

export function SourceBoard({
  servers,
  loading,
  onRefresh,
  detailed,
}: {
  servers: ServerState[] | undefined;
  loading: boolean;
  onRefresh?: () => void;
  detailed?: boolean;
}) {
  return (
    <div>
      {onRefresh && (
        <div className="mb-3 flex justify-end">
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={cn(loading && "animate-spin")} /> Check again
          </Button>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {servers
          ? servers.map((s) => <SourceSign key={s.id} server={s} detailed={detailed} />)
          : [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36" />)}
      </div>
    </div>
  );
}
