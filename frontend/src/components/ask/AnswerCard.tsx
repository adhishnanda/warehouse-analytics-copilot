import { AlertTriangle } from "lucide-react";

import { FeedbackButtons } from "@/components/ask/FeedbackButtons";
import { SqlDisclosure } from "@/components/ask/SqlDisclosure";
import { BarChartCard } from "@/components/charts/BarChartCard";
import { KpiRow } from "@/components/charts/KpiRow";
import { LineChartCard } from "@/components/charts/LineChartCard";
import { ResultTable } from "@/components/charts/ResultTable";
import { StatTile } from "@/components/charts/StatTile";
import type { AskResponse } from "@/lib/types";
import { formatLabel, formatValue } from "@/lib/utils";

function toRecords(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
}

export function AnswerCard({ data }: { data: AskResponse }) {
  if (!data.succeeded) {
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{data.error ?? "The agent could not answer this question."}</span>
        </div>
        {data.sql && <SqlDisclosure sql={data.sql} label="Attempted SQL" />}
        <FeedbackButtons queryId={data.query_id} />
      </div>
    );
  }

  const { columns, rows, chart_kind } = data;
  const records = chart_kind === "bar" || chart_kind === "line" ? toRecords(columns, rows) : [];

  return (
    <div className="space-y-3">
      {chart_kind === "metric" && <StatTile label={formatLabel(columns[0])} value={formatValue(rows[0][0])} />}
      {chart_kind === "kpi_row" && (
        <KpiRow items={columns.map((c, i) => ({ label: formatLabel(c), value: formatValue(rows[0][i]) }))} />
      )}
      {chart_kind === "bar" && (
        <BarChartCard
          data={records}
          xKey={columns[0]}
          yKey={columns[1]}
          valueFormatter={formatValue}
          labelFormatter={formatLabel}
        />
      )}
      {chart_kind === "line" && (
        <LineChartCard
          data={records}
          xKey={columns[0]}
          yKey={columns[1]}
          valueFormatter={formatValue}
          labelFormatter={formatLabel}
        />
      )}
      {chart_kind === "table" && <ResultTable columns={columns} rows={rows} />}

      {data.sql && <SqlDisclosure sql={data.sql} />}

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {data.model} · {data.attempt_count} attempt{data.attempt_count !== 1 ? "s" : ""}
        </span>
        <FeedbackButtons queryId={data.query_id} />
      </div>
    </div>
  );
}
