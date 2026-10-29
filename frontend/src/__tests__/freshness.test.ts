import { describe, expect, it } from "vitest";

import { freshness } from "@/components/chat/source-tags";
import type { SourceRef } from "@/lib/types";
import { formatTime } from "@/lib/utils";

const base: SourceRef = {
  server_id: "cafeteria",
  server_name: "Cafeteria",
  tool: "get_today_menu",
  mode: "imported",
  provider: "json:menu.json",
  data_as_of: null,
  stale: false,
};

describe("freshness", () => {
  it("separates out-of-date, unverifiable and current data", () => {
    expect(freshness({ ...base, stale: true })).toEqual({ label: "out of date", tone: "warn" });
    expect(freshness({ ...base, stale: null })).toEqual({ label: "freshness unverified", tone: "muted" });
    expect(freshness({ ...base, stale: false })).toBeNull();
  });

  it("does not add a freshness warning to demo data (the demo label already says it)", () => {
    expect(freshness({ ...base, mode: "demo", stale: null })).toBeNull();
  });
});

describe("formatTime", () => {
  it("renders in campus time regardless of the browser timezone", () => {
    // 18:30 UTC on 28 Oct is 00:00 on 29 Oct in India.
    expect(formatTime("2026-10-28T18:30:00Z")).toMatch(/29 Oct.*00:00:00 IST/);
  });

  it("returns the raw value for unparseable input and 'never' for empty", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
    expect(formatTime(null)).toBe("never");
  });
});
