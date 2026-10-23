import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", month: "short", day: "numeric" });
}

/** "library__search_books" -> { server: "library", tool: "search_books" } */
export function splitTool(name: string): { server: string; tool: string } {
  const i = name.indexOf("__");
  return i === -1 ? { server: "", tool: name } : { server: name.slice(0, i), tool: name.slice(i + 2) };
}
