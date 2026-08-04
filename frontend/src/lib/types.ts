// Mirrors the Pydantic response models in src/app/api.py and
// src/app/monitoring.py - keep these in sync by hand, there is no
// generated client here.

export type ChartKind = "metric" | "kpi_row" | "bar" | "line" | "table";

export interface AskResponse {
  query_id: string;
  question: string;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  succeeded: boolean;
  error: string | null;
  attempt_count: number;
  model: string;
  chart_kind: ChartKind;
}

export type Vote = "up" | "down";

export interface MonitoringSummary {
  total_queries: number;
  execution_accuracy: number;
  total_cost_usd: number;
  feedback_rate: number;
  helpful_count: number;
  not_helpful_count: number;
  latency_p50_seconds: number;
  latency_p95_seconds: number;
}

export interface TimeseriesPoint {
  date: string;
  query_count: number;
  execution_accuracy: number;
  avg_cost_usd: number;
}

export interface FailureCategory {
  category: string;
  count: number;
}

export interface TraceRow {
  query_id: string;
  timestamp: string;
  question: string;
  model: string;
  succeeded: boolean;
  category: string;
  attempt_count: number;
  latency_seconds: number;
  cost_usd: number;
}

export interface TracesResponse {
  traces: TraceRow[];
  total: number;
}
