interface TooltipEntry {
  dataKey?: string | number;
  value?: number;
  color?: string;
}

interface Props {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  formatter?: (value: number) => string;
  labelFormatter?: (label: string) => string;
}

export function ChartTooltip({ active, payload, label, formatter, labelFormatter }: Props) {
  if (!active || !payload?.length) return null;

  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-medium text-popover-foreground">
        {labelFormatter ? labelFormatter(String(label)) : label}
      </div>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center gap-1.5 text-muted-foreground">
          <span className="size-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span>{formatter && entry.value !== undefined ? formatter(entry.value) : entry.value}</span>
        </div>
      ))}
    </div>
  );
}
