import { ChevronRight, Code2 } from "lucide-react";
import { useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

interface Props {
  sql: string;
  label?: string;
}

export function SqlDisclosure({ sql, label = "Show SQL" }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
        <ChevronRight className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`} />
        <Code2 className="size-3.5" />
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="mt-2 overflow-x-auto rounded-md border bg-muted/50 p-3 font-mono text-xs leading-relaxed text-foreground">
          {sql}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
