import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ChartCard({ title, caption, children }: { title: string; caption?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {children}
        {caption && <p className="mt-2 text-xs text-muted-foreground">{caption}</p>}
      </CardContent>
    </Card>
  );
}
