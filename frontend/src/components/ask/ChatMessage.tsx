import { Bot, User } from "lucide-react";
import type { ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";

export function ChatMessage({ role, children }: { role: "user" | "assistant"; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-3">
      <Avatar className="mt-0.5 size-7 shrink-0">
        <AvatarFallback className={role === "assistant" ? "bg-primary text-primary-foreground" : "bg-muted"}>
          {role === "assistant" ? <Bot className="size-4" /> : <User className="size-4" />}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1 pt-0.5">{children}</div>
    </div>
  );
}
