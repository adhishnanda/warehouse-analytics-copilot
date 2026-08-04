import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getMonitoringTraces } from "@/lib/api";

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function RawTracesTable() {
  const { data } = useQuery({
    queryKey: ["monitoring", "traces"],
    queryFn: () => getMonitoringTraces(50, 0),
  });

  if (!data || data.traces.length === 0) {
    return <p className="text-sm text-muted-foreground">No traces logged yet.</p>;
  }

  return (
    <div className="max-h-96 overflow-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Timestamp</TableHead>
            <TableHead>Question</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Attempts</TableHead>
            <TableHead>Latency (s)</TableHead>
            <TableHead>Cost (USD)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.traces.map((trace) => (
            <TableRow key={trace.query_id}>
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatTimestamp(trace.timestamp)}
              </TableCell>
              <TableCell className="max-w-xs truncate">{trace.question}</TableCell>
              <TableCell className="text-xs">{trace.model}</TableCell>
              <TableCell>
                <Badge variant={trace.succeeded ? "secondary" : "destructive"}>
                  {trace.succeeded ? "succeeded" : trace.category}
                </Badge>
              </TableCell>
              <TableCell>{trace.attempt_count}</TableCell>
              <TableCell>{trace.latency_seconds.toFixed(1)}</TableCell>
              <TableCell>${trace.cost_usd.toFixed(4)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
