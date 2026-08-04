import { useMutation } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { submitFeedback } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Vote } from "@/lib/types";

interface Props {
  queryId: string;
}

export function FeedbackButtons({ queryId }: Props) {
  const [vote, setVote] = useState<Vote | null>(null);
  const mutation = useMutation({
    mutationFn: (nextVote: Vote) => submitFeedback(queryId, nextVote),
    onSuccess: (_, nextVote) => setVote(nextVote),
  });

  return (
    <div className="flex items-center gap-1">
      <Button
        variant={vote === "up" ? "default" : "ghost"}
        size="icon-sm"
        disabled={vote !== null}
        onClick={() => mutation.mutate("up")}
        aria-label="Helpful"
      >
        <ThumbsUp className={cn("size-3.5", vote === "up" && "fill-current")} />
      </Button>
      <Button
        variant={vote === "down" ? "default" : "ghost"}
        size="icon-sm"
        disabled={vote !== null}
        onClick={() => mutation.mutate("down")}
        aria-label="Not helpful"
      >
        <ThumbsDown className={cn("size-3.5", vote === "down" && "fill-current")} />
      </Button>
      {vote && <span className="ml-1 text-xs text-muted-foreground">Thanks for the feedback</span>}
    </div>
  );
}
