import { useMutation } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AnswerCard } from "@/components/ask/AnswerCard";
import { ChatMessage } from "@/components/ask/ChatMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { askQuestion } from "@/lib/api";
import type { AskResponse } from "@/lib/types";

const SUGGESTED_QUESTIONS = [
  "How many orders do we have in total?",
  "What is total revenue by region?",
  "What is our repeat customer rate?",
];

type Message = { role: "user"; content: string } | { role: "assistant"; data: AskResponse };

export function AskPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const mutation = useMutation({
    mutationFn: askQuestion,
    onSuccess: (data) => setMessages((prev) => [...prev, { role: "assistant", data }]),
    onError: (error: Error) => toast.error(error.message),
  });

  function ask(question: string) {
    if (!question.trim() || mutation.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    mutation.mutate(question);
  }

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-hidden px-4">
      <ScrollArea className="min-h-0 flex-1">
        <div className="py-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center gap-4 py-16 text-center">
              <div>
                <h2 className="text-lg font-medium">Ask a business question</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Answers are grounded in a governed semantic layer, not a raw schema dump.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTED_QUESTIONS.map((question) => (
                  <Button key={question} variant="outline" size="sm" className="rounded-full" onClick={() => ask(question)}>
                    {question}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, i) =>
            message.role === "user" ? (
              // eslint-disable-next-line react/no-array-index-key
              <ChatMessage key={i} role="user">
                <p className="text-sm">{message.content}</p>
              </ChatMessage>
            ) : (
              // eslint-disable-next-line react/no-array-index-key
              <ChatMessage key={i} role="assistant">
                <AnswerCard data={message.data} />
              </ChatMessage>
            ),
          )}

          {mutation.isPending && (
            <ChatMessage role="assistant">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                Retrieving context and generating SQL...
              </div>
            </ChatMessage>
          )}
        </div>
      </ScrollArea>

      <form
        className="flex items-center gap-2 border-t py-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a business question about the warehouse"
          disabled={mutation.isPending}
        />
        <Button type="submit" size="icon" disabled={mutation.isPending || !input.trim()} aria-label="Send">
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  );
}
