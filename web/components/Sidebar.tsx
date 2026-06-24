"use client";

import { useState } from "react";
import { MessageSquare, MoreHorizontal, Pin, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { getSessionTitle } from "@/lib/session";
import type { Session } from "@/lib/types";

type SidebarProps = {
  sessions: Session[];
  activeSessionId: string | null;
  onCreateSession: () => void;
  onDeleteSession: (sessionId: string) => void;
  onPinSession: (sessionId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onUnpinSession: (sessionId: string) => void;
};

export function Sidebar({
  sessions,
  activeSessionId,
  onCreateSession,
  onDeleteSession,
  onPinSession,
  onSelectSession,
  onUnpinSession
}: SidebarProps) {
  const [openMenuSessionId, setOpenMenuSessionId] = useState<string | null>(null);

  const pinnedSessions = sessions.filter((session) => session.pinned);
  const regularSessions = sessions.filter((session) => !session.pinned);

  function renderSessionItem(session: Session) {
    const isActive = session.id === activeSessionId;
    const menuIsOpen = openMenuSessionId === session.id;

    return (
      <div
        key={session.id}
        className={cn(
          "relative flex items-center gap-1 rounded-md pr-1 transition-colors hover:bg-muted",
          isActive && "bg-muted font-medium"
        )}
      >
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left text-sm"
          onClick={() => onSelectSession(session.id)}
        >
          <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">{getSessionTitle(session)}</span>
          {session.pinned ? (
            <Pin className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
          ) : null}
        </button>

        <button
          type="button"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
          aria-label="会话菜单"
          onClick={() => setOpenMenuSessionId(menuIsOpen ? null : session.id)}
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>

        {menuIsOpen ? (
          <div className="absolute right-1 top-9 z-10 w-32 rounded-md border bg-white py-1 text-sm shadow-md">
            <button
              type="button"
              className="w-full px-3 py-2 text-left hover:bg-muted"
              onClick={() => {
                setOpenMenuSessionId(null);
                if (session.pinned) {
                  onUnpinSession(session.id);
                } else {
                  onPinSession(session.id);
                }
              }}
            >
              {session.pinned ? "取消置顶" : "置顶"}
            </button>
            <button
              type="button"
              className="w-full px-3 py-2 text-left text-destructive hover:bg-muted"
              onClick={() => {
                setOpenMenuSessionId(null);
                if (window.confirm("确认删除该会话？删除后不可恢复。")) {
                  onDeleteSession(session.id);
                }
              }}
            >
              删除
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  function renderSessionGroup(label: string, groupSessions: Session[]) {
    if (groupSessions.length === 0) {
      return null;
    }

    return (
      <div className="space-y-1">
        <div className="px-3 py-1 text-xs font-medium text-muted-foreground">{label}</div>
        {groupSessions.map(renderSessionItem)}
      </div>
    );
  }

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r bg-white">
      <div className="border-b px-4 py-4">
        <Button className="w-full justify-start" onClick={onCreateSession}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          新建会话
        </Button>
      </div>

      <ScrollArea className="flex-1 px-3 py-3">
        <div className="space-y-3">
          {renderSessionGroup("置顶", pinnedSessions)}
          {renderSessionGroup("会话", regularSessions)}
        </div>
      </ScrollArea>
    </aside>
  );
}
