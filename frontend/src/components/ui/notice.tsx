import { AlertTriangle, Info, XCircle } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

const ICONS = { info: Info, warn: AlertTriangle, bad: XCircle };
const TONES = { info: "border-rule text-ink-muted", warn: "border-warn/40 text-warn", bad: "border-bad/40 text-bad" };

export function Notice({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warn" | "bad";
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const Icon = ICONS[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cn("flex gap-3 rounded-md border bg-panel p-3 text-sm", TONES[tone], className)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="text-ink">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className="text-ink-muted">{children}</div>}
      </div>
    </div>
  );
}
