import { Suspense } from "react";

import { TracesView } from "./traces-view";

export default function TracesPage() {
  return (
    <Suspense>
      <TracesView />
    </Suspense>
  );
}
