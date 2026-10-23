import { BookOpen, CalendarDays, GraduationCap, Utensils, type LucideIcon } from "lucide-react";

export interface ServiceMeta {
  id: string;
  name: string;
  icon: LucideIcon;
  /** CSS variable holding the service's wayfinding colour */
  color: string;
}

export const SERVICES: Record<string, ServiceMeta> = {
  library: { id: "library", name: "Library", icon: BookOpen, color: "var(--svc-library)" },
  events: { id: "events", name: "Events", icon: CalendarDays, color: "var(--svc-events)" },
  cafeteria: { id: "cafeteria", name: "Cafeteria", icon: Utensils, color: "var(--svc-cafeteria)" },
  academics: { id: "academics", name: "Academics", icon: GraduationCap, color: "var(--svc-academics)" },
};

export function serviceMeta(id: string | null | undefined): ServiceMeta {
  return (
    (id && SERVICES[id]) || { id: id ?? "unknown", name: id ?? "Unknown", icon: GraduationCap, color: "var(--ink-muted)" }
  );
}
