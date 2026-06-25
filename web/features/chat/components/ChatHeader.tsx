import { Wifi, WifiOff } from "lucide-react";
import type { ConnectionStatus, Session } from "../model/chat.types";

type ChatHeaderProps = {
  activeSession: Session | null;
  connectionStatus: ConnectionStatus;
};

function getConnectionLabel(status: ConnectionStatus) {
  if (status === "connected") {
    return "已连接";
  }

  if (status === "connecting") {
    return "连接中";
  }

  return "未连接";
}

export function ChatHeader({ activeSession, connectionStatus }: ChatHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b bg-white px-6">
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold">Nanobot Web</h1>
        <p className="text-sm text-muted-foreground">
          {activeSession ? activeSession.id : "暂无会话"}
        </p>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {connectionStatus === "connected" ? (
          <Wifi className="h-4 w-4 text-primary" aria-hidden="true" />
        ) : (
          <WifiOff className="h-4 w-4 text-destructive" aria-hidden="true" />
        )}
        {getConnectionLabel(connectionStatus)}
      </div>
    </header>
  );
}
