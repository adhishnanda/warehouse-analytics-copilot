import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ChartTooltip } from "@/components/charts/ChartTooltip";
import { CATEGORICAL_PALETTE } from "@/components/charts/palette";

interface Props<T> {
  data: T[];
  xKey: Extract<keyof T, string>;
  yKey: Extract<keyof T, string>;
  color?: string;
  valueFormatter?: (value: number) => string;
  labelFormatter?: (label: string) => string;
}

export function BarChartCard<T extends object>({
  data,
  xKey,
  yKey,
  color = CATEGORICAL_PALETTE[0],
  valueFormatter,
  labelFormatter,
}: Props<T>) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis
          dataKey={xKey}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
          width={48}
        />
        <Tooltip
          cursor={{ fill: "var(--muted)", opacity: 0.4 }}
          content={<ChartTooltip formatter={valueFormatter} labelFormatter={labelFormatter} />}
        />
        <Bar dataKey={yKey} fill={color} radius={[4, 4, 0, 0]} maxBarSize={48} />
      </BarChart>
    </ResponsiveContainer>
  );
}
