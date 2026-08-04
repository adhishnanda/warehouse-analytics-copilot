import { useQuery } from "@tanstack/react-query";

import { BarChartCard } from "@/components/charts/BarChartCard";
import { LineChartCard } from "@/components/charts/LineChartCard";
import { STATUS_CRITICAL, STATUS_GOOD } from "@/components/charts/palette";
import { ChartCard } from "@/components/monitoring/ChartCard";
import { KpiCard } from "@/components/monitoring/KpiCard";
import { RawTracesTable } from "@/components/monitoring/RawTracesTable";
import { RefreshButton } from "@/components/monitoring/RefreshButton";
import { Skeleton } from "@/components/ui/skeleton";
import { getMonitoringFailures, getMonitoringSummary, getMonitoringTimeseries } from "@/lib/api";
import { formatLabel } from "@/lib/utils";

const currency = (v: number) => `$${v.toFixed(4)}`;
const percent = (v: number) => `${(v * 100).toFixed(0)}%`;
const seconds = (v: number) => `${v.toFixed(1)}s`;

export function MonitoringPage() {
  const summary = useQuery({ queryKey: ["monitoring", "summary"], queryFn: getMonitoringSummary });
  const timeseries = useQuery({ queryKey: ["monitoring", "timeseries"], queryFn: getMonitoringTimeseries });
  const failures = useQuery({ queryKey: ["monitoring", "failures"], queryFn: getMonitoringFailures });

  const points = timeseries.data?.points ?? [];
  const noTelemetry = summary.data?.total_queries === 0;

  return (
    <div className="mx-auto w-full min-h-0 max-w-5xl flex-1 space-y-6 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Live usage metrics from the deployed agent, built from the request trace log via the dlt pipeline.
        </p>
        <RefreshButton />
      </div>

      {noTelemetry && (
        <p className="rounded-md border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
          No telemetry yet - ask a question in the Ask tab first, then refresh.
        </p>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {summary.isLoading ? (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-20" />)
        ) : summary.data ? (
          <>
            <KpiCard label="Total queries" value={summary.data.total_queries.toLocaleString()} />
            <KpiCard label="Execution accuracy" value={percent(summary.data.execution_accuracy)} />
            <KpiCard label="Total cost" value={currency(summary.data.total_cost_usd)} />
            <KpiCard label="Feedback rate" value={percent(summary.data.feedback_rate)} />
            <KpiCard label="p50 latency" value={seconds(summary.data.latency_p50_seconds)} />
            <KpiCard label="p95 latency" value={seconds(summary.data.latency_p95_seconds)} />
          </>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title="Queries over time">
          {points.length > 0 ? (
            <BarChartCard data={points} xKey="date" yKey="query_count" labelFormatter={() => "Date"} />
          ) : (
            <Skeleton className="h-[260px]" />
          )}
        </ChartCard>

        <ChartCard title="Execution accuracy over time">
          {points.length > 0 ? (
            <LineChartCard
              data={points}
              xKey="date"
              yKey="execution_accuracy"
              color={STATUS_GOOD}
              valueFormatter={percent}
            />
          ) : (
            <Skeleton className="h-[260px]" />
          )}
        </ChartCard>

        <ChartCard
          title="Cost per query"
          caption="Local Ollama has no billable usage; only paid-backend queries contribute non-zero cost."
        >
          {points.length > 0 ? (
            <BarChartCard data={points} xKey="date" yKey="avg_cost_usd" valueFormatter={currency} />
          ) : (
            <Skeleton className="h-[260px]" />
          )}
        </ChartCard>

        <ChartCard title="Top failure categories">
          {failures.data && failures.data.categories.length > 0 ? (
            <BarChartCard
              data={failures.data.categories}
              xKey="category"
              yKey="count"
              color={STATUS_CRITICAL}
              labelFormatter={formatLabel}
            />
          ) : (
            <p className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
              No failures logged yet.
            </p>
          )}
        </ChartCard>
      </div>

      <ChartCard title="Raw traces">
        <RawTracesTable />
      </ChartCard>
    </div>
  );
}
