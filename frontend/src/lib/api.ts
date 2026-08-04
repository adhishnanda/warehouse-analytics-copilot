import type {
  AskResponse,
  FailureCategory,
  MonitoringSummary,
  TimeseriesPoint,
  TracesResponse,
  Vote,
} from "@/lib/types";

// Relative paths: proxied to :8000 by Vite in dev (see vite.config.ts),
// same-origin in production since FastAPI serves this build directly.
const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${init?.method ?? "GET"} ${path} failed (${response.status}): ${body}`);
  }
  return response.json() as Promise<T>;
}

export function askQuestion(question: string): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function submitFeedback(queryId: string, vote: Vote): Promise<void> {
  return request<{ ok: boolean }>("/feedback", {
    method: "POST",
    body: JSON.stringify({ query_id: queryId, vote }),
  }).then(() => undefined);
}

export function getMonitoringSummary(): Promise<MonitoringSummary> {
  return request<MonitoringSummary>("/monitoring/summary");
}

export function getMonitoringTimeseries(): Promise<{ points: TimeseriesPoint[] }> {
  return request<{ points: TimeseriesPoint[] }>("/monitoring/timeseries");
}

export function getMonitoringFailures(): Promise<{ categories: FailureCategory[] }> {
  return request<{ categories: FailureCategory[] }>("/monitoring/failures");
}

export function getMonitoringTraces(limit = 100, offset = 0): Promise<TracesResponse> {
  return request<TracesResponse>(`/monitoring/traces?limit=${limit}&offset=${offset}`);
}

export function refreshMonitoring(): Promise<void> {
  return request<{ ok: boolean }>("/monitoring/refresh", { method: "POST" }).then(() => undefined);
}
