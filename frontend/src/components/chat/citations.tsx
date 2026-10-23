import { FileText } from "lucide-react";

import type { Citation } from "@/lib/types";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium">Handbook evidence</h3>
      <ul className="space-y-2">
        {citations.map((c) => (
          <li key={c.citation_id}>
            <details className="group rounded-md border border-rule bg-panel">
              <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-2 text-sm">
                <FileText className="mt-0.5 size-4 shrink-0" style={{ color: "var(--svc-academics)" }} aria-hidden />
                <span className="flex-1">
                  <span className="font-medium">
                    [{c.number}] {c.document_title}, page {c.page}
                  </span>
                  {c.section && <span className="block text-xs text-ink-muted">{c.section}</span>}
                </span>
                <span className="text-xs text-ink-muted group-open:hidden">Show excerpt</span>
                <span className="hidden text-xs text-ink-muted group-open:inline">Hide excerpt</span>
              </summary>
              <div className="border-t border-rule px-3 py-2 text-sm">
                <blockquote className="border-l-2 pl-3 text-ink" style={{ borderColor: "var(--svc-academics)" }}>
                  {c.excerpt}
                </blockquote>
                <p className="mt-2 text-xs text-ink-muted">
                  {c.source_filename}, version {c.document_version}, passage {c.citation_id}
                </p>
              </div>
            </details>
          </li>
        ))}
      </ul>
    </div>
  );
}
