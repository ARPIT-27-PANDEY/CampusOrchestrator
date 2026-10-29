import type { SourceRef } from "@/lib/types";
import { serviceMeta } from "@/lib/services";
import { formatTime } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";

const MODE_TEXT: Record<string, string> = {
  demo: "Demo data",
  imported: "Imported snapshot",
  live: "Live source",
};

/** stale=true -> out of date; stale=null on non-demo data -> cannot be verified; otherwise current. */
export function freshness(s: SourceRef): { label: string; tone: "warn" | "muted" } | null {
  if (s.stale === true) return { label: "out of date", tone: "warn" };
  if (s.stale == null && s.mode !== "demo" && s.mode != null) return { label: "freshness unverified", tone: "muted" };
  return null;
}

function describe(s: SourceRef): string {
  return [
    s.provider && `Provider: ${s.provider}`,
    s.retrieved_at && `Checked: ${formatTime(s.retrieved_at)}`,
    s.data_as_of && `Source dated: ${s.data_as_of}`,
    s.staleness_reason,
    s.note,
  ]
    .filter(Boolean)
    .join("\n");
}

/** One tag per system that contributed, stating whether its data is demo, imported or live, and how fresh. */
export function SourceTags({ sources }: { sources: SourceRef[] }) {
  const byServer = new Map<string, SourceRef>();
  for (const s of sources) byServer.set(s.server_id, s);
  if (!byServer.size) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Data sources">
      {[...byServer.values()].map((s) => {
        const svc = serviceMeta(s.server_id);
        const Icon = svc.icon;
        const mode = s.mode ?? "unknown";
        const fresh = freshness(s);
        return (
          <li key={s.server_id}>
            <Badge
              tone={fresh?.tone === "warn" ? "warn" : mode === "live" ? "ok" : mode === "demo" ? "demo" : "warn"}
              className="text-[12px]"
              title={describe(s) || undefined}
            >
              <Icon className="size-3.5" style={{ color: svc.color }} aria-hidden />
              <span className="text-ink">{svc.name}</span>
              <span>{MODE_TEXT[mode] ?? "Unlabelled source"}</span>
              {fresh ? (
                <span className={fresh.tone === "warn" ? "font-medium text-warn" : "text-ink-muted"}>{fresh.label}</span>
              ) : null}
              {s.retrieved_at ? <span className="text-ink-muted">checked {formatTime(s.retrieved_at)}</span> : null}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}
