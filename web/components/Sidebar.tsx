import { MessageSquare, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { getSessionTitle } from "@/lib/session";
import type { Session } from "@/lib/types";

type SidebarProps = {
  sessions: Session[];
  activeSessionId: string | null;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
};

export function Sidebar({
  sessions,
  activeSessionId,
  onCreateSession,
  onSelectSession
}: SidebarProps) {
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r bg-white">
      <div className="border-b px-4 py-4">
        <Button className="w-full justify-start" onClick={onCreateSession}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          新建会话
        </Button>
      </div>

      <ScrollArea className="flex-1 px-3 py-3">
        <div className="space-y-1">
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;

            return (
              <button
                key={session.id}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                  isActive && "bg-muted font-medium"
                )}
                onClick={() => onSelectSession(session.id)}
              >
                <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{getSessionTitle(session)}</span>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </aside>
  );
}
