import { Bot, UserRound } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Session } from "../model/chat.types";

type ConversationViewProps = {
  session: Session | null;
};

export function ConversationView({ session }: ConversationViewProps) {
  return (
    <ScrollArea className="min-h-0 flex-1 px-6 py-6">
      {!session || session.messages.length === 0 ? (
        <div className="flex h-full min-h-80 items-center justify-center text-center text-sm text-muted-foreground">
          开始一次新的 Nanobot 对话
        </div>
      ) : (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
          {session.messages.map((message) => {
            const isUser = message.role === "user";

            return (
              <div
                key={message.id}
                className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}
              >
                {!isUser ? (
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <Bot className="h-4 w-4" aria-hidden="true" />
                  </div>
                ) : null}
                <div
                  className={cn(
                    "max-w-[min(42rem,80%)] whitespace-pre-wrap break-words rounded-md px-4 py-3 text-sm leading-6 shadow-sm",
                    isUser
                      ? "bg-primary text-primary-foreground"
                      : "border bg-white text-foreground"
                  )}
                >
                  {message.content}
                </div>
                {isUser ? (
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <UserRound className="h-4 w-4" aria-hidden="true" />
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </ScrollArea>
  );
}
