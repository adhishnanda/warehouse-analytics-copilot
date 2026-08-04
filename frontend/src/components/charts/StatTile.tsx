interface Props {
  label: string;
  value: string;
}

export function StatTile({ label, value }: Props) {
  return (
    <div>
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}
