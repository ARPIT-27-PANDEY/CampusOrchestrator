"use client";

import { useSearchParams } from "next/navigation";

import { ChatSession } from "@/components/chat/chat-session";

export function ChatFromSearchParams() {
  const q = useSearchParams().get("q") ?? undefined;
  return <ChatSession initialQuery={q} />;
}
