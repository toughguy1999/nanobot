"use client";

import { useEffect, useState } from "react";
import {
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Plus
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useSidebarPreference } from "../hooks/useSidebarPreference";
import type { Session } from "../model/chat.types";
import { getSessionTitle } from "../model/session";

const sidebarItemClass =
  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted";

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
  const [showExpandIcon, setShowExpandIcon] = useState(false);
  const { isCollapsed, isInitialized, collapse, expand } = useSidebarPreference();
  const pinnedSessions = sessions.filter((session) => session.pinned);
  const regularSessions = sessions.filter((session) => !session.pinned);

  useEffect(() => {
    if (isCollapsed) {
      setOpenMenuSessionId(null);
    }
  }, [isCollapsed]);

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
          className={cn(sidebarItemClass, "min-w-0 flex-1 pr-0")}
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
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col overflow-hidden border-r bg-white",
        isCollapsed ? "w-14" : "w-72",
        isInitialized && "transition-[width] duration-200 ease-in-out"
      )}
    >
      {isCollapsed ? (
        <div className="flex justify-center px-2 py-3">
          <Button
            variant="ghost"
            size="icon"
            aria-label="展开侧边栏"
            onClick={expand}
            onMouseEnter={() => setShowExpandIcon(true)}
            onMouseLeave={() => setShowExpandIcon(false)}
            onFocus={() => setShowExpandIcon(true)}
            onBlur={() => setShowExpandIcon(false)}
          >
            <span className="flex h-4 w-4 items-center justify-center" aria-hidden="true">
              {showExpandIcon ? (
                <PanelLeftOpen className="h-4 w-4" data-testid="sidebar-expand-icon" />
              ) : (
                <span>🐈</span>
              )}
            </span>
          </Button>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between px-4 pb-2 pt-3">
            <div className="flex items-center gap-2 font-semibold">
              <span aria-hidden="true">🐈</span>
              <span>Nanobot</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label="收起侧边栏"
              onClick={collapse}
            >
              <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="px-3 pb-1">
            <button type="button" className={sidebarItemClass} onClick={onCreateSession}>
              <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>新建会话</span>
            </button>
          </div>

          <ScrollArea className="flex-1 px-3 py-3">
            <div className="space-y-3">
              {renderSessionGroup("置顶", pinnedSessions)}
              {renderSessionGroup("会话", regularSessions)}
            </div>
          </ScrollArea>
        </>
      )}
    </aside>
  );
}
