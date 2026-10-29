import { Suspense } from "react";

import { AuthGate } from "@/components/auth-gate";

import { ChatFromSearchParams } from "./search-params";

export default function ChatPage() {
  return (
    <AuthGate what="the assistant">
      <Suspense>
        <ChatFromSearchParams />
      </Suspense>
    </AuthGate>
  );
}
