import { Suspense } from "react";

import { ChatFromSearchParams } from "./search-params";

export default function ChatPage() {
  return (
    <Suspense>
      <ChatFromSearchParams />
    </Suspense>
  );
}
