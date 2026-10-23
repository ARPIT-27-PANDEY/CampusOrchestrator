import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium", {
  variants: {
    tone: {
      neutral: "bg-ink/7 text-ink-muted",
      ok: "bg-ok/12 text-ok",
      warn: "bg-warn/14 text-warn",
      bad: "bg-bad/12 text-bad",
      demo: "demo-hatch border border-rule text-ink-muted",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
