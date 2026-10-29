import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Campus timezone for displaying timestamps. Dates of menus and events come from the tools, never from here. */
export const CAMPUS_TIME_ZONE = process.env.NEXT_PUBLIC_CAMPUS_TIMEZONE || "Asia/Kolkata";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/** Format an ISO timestamp in the campus timezone (not the browser's), labelled with the zone. */
export function formatTime(iso: string | null | undefined, timeZone: string = CAMPUS_TIME_ZONE): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const text = d.toLocaleString("en-IN", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    month: "short",
    day: "numeric",
    hour12: false,
  });
  return `${text} ${timeZone === "Asia/Kolkata" ? "IST" : timeZone}`;
}

/** "library__search_books" -> { server: "library", tool: "search_books" } */
export function splitTool(name: string): { server: string; tool: string } {
  const i = name.indexOf("__");
  return i === -1 ? { server: "", tool: name } : { server: name.slice(0, i), tool: name.slice(i + 2) };
}
