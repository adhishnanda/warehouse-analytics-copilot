import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/ui/skeleton";

const AskPage = lazy(() => import("@/components/ask/AskPage").then((m) => ({ default: m.AskPage })));
const MonitoringPage = lazy(() =>
  import("@/components/monitoring/MonitoringPage").then((m) => ({ default: m.MonitoringPage })),
);

function PageFallback() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Navigate to="/ask" replace />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/monitoring" element={<MonitoringPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
