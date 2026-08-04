import { Card, CardContent } from "@/components/ui/card";

interface Props {
  label: string;
  value: string;
  valueClassName?: string;
}

export function KpiCard({ label, value, valueClassName }: Props) {
  return (
    <Card>
      <CardContent className="py-1">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className={`mt-1 text-2xl font-semibold tracking-tight ${valueClassName ?? ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
