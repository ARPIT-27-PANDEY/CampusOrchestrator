import type { Metadata } from "next";
import "./globals.css";

import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "CampusOS AI",
  description: "Ask one question across the campus library, events, cafeteria and academic handbook.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
