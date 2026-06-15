"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Wifi, WifiOff } from "lucide-react";
import { ConversationView } from "@/components/ConversationView";
import { ErrorBanner } from "@/components/ErrorBanner";
import { MessageInput } from "@/components/MessageInput";
import { Sidebar } from "@/components/Sidebar";
import { appendMessageToSession, createMessage, createSession } from "@/lib/session";
import {
  loadActiveSessionId,
  loadSessions,
  saveActiveSessionId,
  saveSessions
} from "@/lib/storage";
import type { ConnectionStatus, Session } from "@/lib/types";
import { checkServerStatus, getWebSocketUrl, parseServerMessage } from "@/lib/websocket";

function getConnectionLabel(status: ConnectionStatus) {
  if (status === "connected") {
    return "已连接";
  }

  if (status === "connecting") {
    return "连接中";
  }

  return "未连接";
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");

  const websocketRef = useRef<WebSocket | null>(null);
  const pendingSessionIdsRef = useRef<string[]>([]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [activeSessionId, sessions]
  );

  useEffect(() => {
    const storedSessions = loadSessions();
    const storedActiveSessionId = loadActiveSessionId();

    if (storedSessions.length === 0) {
      const firstSession = createSession();
      setSessions([firstSession]);
      setActiveSessionId(firstSession.id);
      return;
    }

    setSessions(storedSessions);
    setActiveSessionId(
      storedSessions.some((session) => session.id === storedActiveSessionId)
        ? storedActiveSessionId
        : storedSessions[0].id
    );
  }, []);

  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  useEffect(() => {
    saveActiveSessionId(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    let cancelled = false;

    async function connect() {
      setConnectionStatus("connecting");

      try {
        await checkServerStatus();

        if (cancelled) {
          return;
        }

        const websocket = new WebSocket(getWebSocketUrl());
        websocketRef.current = websocket;

        websocket.onopen = () => {
          setConnectionStatus("connected");
          setErrorMessage(null);
        };

        websocket.onmessage = (event) => {
          try {
            const message = parseServerMessage(String(event.data));

            if ("error" in message) {
              setErrorMessage(message.error);
              return;
            }

            const sessionId = pendingSessionIdsRef.current.shift();
            if (!sessionId) {
              return;
            }

            setSessions((currentSessions) =>
              appendMessageToSession(
                currentSessions,
                sessionId,
                createMessage("assistant", message.content)
              )
            );
          } catch {
            setErrorMessage("无法解析服务端返回的消息");
          }
        };

        websocket.onerror = () => {
          setConnectionStatus("disconnected");
          setErrorMessage("WebSocket 连接失败，请确认 nanobot web channel 正在运行");
        };

        websocket.onclose = (event) => {
          if (cancelled) {
            return;
          }

          setConnectionStatus("disconnected");
          if (event.code !== 1000) {
            setErrorMessage("WebSocket 连接已断开，请刷新页面后重试");
          }
        };
      } catch (error) {
        if (cancelled) {
          return;
        }

        setConnectionStatus("disconnected");
        setErrorMessage(error instanceof Error ? error.message : "服务端不可用");
      }
    }

    connect();

    return () => {
      cancelled = true;
      websocketRef.current?.close(1000);
      websocketRef.current = null;
    };
  }, []);

  function handleCreateSession() {
    const session = createSession();
    setSessions((currentSessions) => [session, ...currentSessions]);
    setActiveSessionId(session.id);
    setErrorMessage(null);
  }

  function handleSend() {
    const content = inputValue.trim();
    const websocket = websocketRef.current;

    if (!content || !activeSessionId || connectionStatus !== "connected") {
      return;
    }

    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
      setConnectionStatus("disconnected");
      setErrorMessage("WebSocket 未连接，消息未发送");
      return;
    }

    const sendingSessionId = activeSessionId;
    const userMessage = createMessage("user", content);

    setSessions((currentSessions) =>
      appendMessageToSession(currentSessions, sendingSessionId, userMessage)
    );
    setInputValue("");
    setErrorMessage(null);

    try {
      pendingSessionIdsRef.current.push(sendingSessionId);
      websocket.send(
        JSON.stringify({
          sessionId: sendingSessionId,
          content
        })
      );
    } catch {
      pendingSessionIdsRef.current.pop();
      setConnectionStatus("disconnected");
      setErrorMessage("消息发送失败，请检查 WebSocket 连接");
    }
  }

  const inputDisabled = !activeSession || connectionStatus !== "connected";

  return (
    <main className="flex h-screen min-h-screen overflow-hidden bg-background">
      <Sidebar
        activeSessionId={activeSessionId}
        sessions={sessions}
        onCreateSession={handleCreateSession}
        onSelectSession={setActiveSessionId}
      />

      <section className="flex min-w-0 flex-1 flex-col">
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

        <div className="shrink-0 px-6 pt-4">
          <ErrorBanner message={errorMessage} onDismiss={() => setErrorMessage(null)} />
        </div>

        <ConversationView session={activeSession} />

        <MessageInput
          disabled={inputDisabled}
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
        />
      </section>
    </main>
  );
}
