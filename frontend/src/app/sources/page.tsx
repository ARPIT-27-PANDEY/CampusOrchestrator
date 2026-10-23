"use client";

import { useState } from "react";

import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";

import { SourceBoard } from "@/components/sources/source-board";
import { Notice } from "@/components/ui/notice";

export default function SourcesPage() {
  const [refresh, setRefresh] = useState(false);
  const sources = useApi((s) => api.sources(refresh, s), { key: String(refresh) });
  return (
    <div className="px-4 py-6 md:px-10 md:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Campus sources</h1>
      <p className="mt-2 max-w-[72ch] text-ink-muted">
        Each system is a separate MCP server. Status comes from a real discovery request; nothing here is assumed.
        Hatched panels serve simulated demo data.
      </p>
      <div className="mt-6">
        {sources.error && (
          <Notice tone="bad" title="Can't load source status" className="mb-4">
            {sources.error.message}
          </Notice>
        )}
        <SourceBoard
          servers={sources.data?.servers}
          loading={sources.loading}
          detailed
          onRefresh={() => {
            setRefresh(true);
            sources.reload();
          }}
        />
        {sources.data && (
          <p className="mt-4 text-[13px] text-ink-muted">{sources.data.tool_count} tools in the registry.</p>
        )}
      </div>
    </div>
  );
}
