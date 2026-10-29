import { Suspense } from "react";

import { AuthGate } from "@/components/auth-gate";

import { TracesView } from "./traces-view";

export default function TracesPage() {
  return (
    <AuthGate what="execution traces">
      <Suspense>
        <TracesView />
      </Suspense>
    </AuthGate>
  );
}
