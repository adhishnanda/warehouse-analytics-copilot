import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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

export function LineChartCard<T extends object>({
  data,
  xKey,
  yKey,
  color = CATEGORICAL_PALETTE[0],
  valueFormatter,
  labelFormatter,
}: Props<T>) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
        <Tooltip content={<ChartTooltip formatter={valueFormatter} labelFormatter={labelFormatter} />} />
        <Line
          type="monotone"
          dataKey={yKey}
          stroke={color}
          strokeWidth={2}
          dot={{ r: 3, fill: color, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
