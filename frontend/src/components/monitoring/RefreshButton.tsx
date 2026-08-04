import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { refreshMonitoring } from "@/lib/api";

export function RefreshButton() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: refreshMonitoring,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
      toast.success("Telemetry refreshed");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Button variant="outline" size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
      <RefreshCw className={`size-3.5 ${mutation.isPending ? "animate-spin" : ""}`} />
      Refresh data
    </Button>
  );
}
