import type { SourceRef } from "@/lib/types";
import { serviceMeta } from "@/lib/services";

import { Badge } from "@/components/ui/badge";

const MODE_TEXT: Record<string, string> = {
  demo: "Demo data",
  imported: "Imported file",
  live: "Live source",
};

/** One tag per system that contributed, stating whether its data is demo, imported or live. */
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
        return (
          <li key={s.server_id}>
            <Badge tone={mode === "live" ? "ok" : mode === "demo" ? "demo" : "warn"} className="text-[12px]">
              <Icon className="size-3.5" style={{ color: svc.color }} aria-hidden />
              <span className="text-ink">{svc.name}</span>
              <span>{MODE_TEXT[mode] ?? "Unlabelled source"}</span>
              {s.stale ? <span className="text-warn">may be outdated</span> : null}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}
