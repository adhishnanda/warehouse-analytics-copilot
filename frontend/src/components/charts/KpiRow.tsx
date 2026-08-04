import { StatTile } from "@/components/charts/StatTile";

interface Props {
  items: { label: string; value: string }[];
}

export function KpiRow({ items }: Props) {
  return (
    <div className="flex flex-wrap gap-6">
      {items.map((item) => (
        <StatTile key={item.label} label={item.label} value={item.value} />
      ))}
    </div>
  );
}
