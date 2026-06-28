"use client";

import { useEffect, useRef, useState } from "react";
import type {
  AssistantMessageEvent,
  ChatAttachment,
  ConnectionStatus,
  DraftAttachment
} from "../model/chat.types";
import {
  getWebSocketUrl,
  parseServerMessage,
  serializeClientMessage
} from "../services/chatWebSocket";

type UseChatWebSocketOptions = {
  enabled: boolean;
  onMessage: (message: AssistantMessageEvent) => void;
  onError: (message: string) => void;
};

export function useChatWebSocket({ enabled, onMessage, onError }: UseChatWebSocketOptions) {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const websocketRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
  }, [onError, onMessage]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let cancelled = false;
    setConnectionStatus("connecting");

    const websocket = new WebSocket(getWebSocketUrl());
    websocketRef.current = websocket;

    websocket.onopen = () => {
      setConnectionStatus("connected");
      onErrorRef.current("");
    };

    websocket.onmessage = (event) => {
      try {
        const message = parseServerMessage(String(event.data));

        if ("error" in message) {
          onErrorRef.current(message.error);
          return;
        }

        onMessageRef.current(message);
      } catch {
        onErrorRef.current("无法解析服务端返回的消息");
      }
    };

    websocket.onerror = () => {
      setConnectionStatus("disconnected");
      onErrorRef.current("WebSocket 连接失败，请确认 nanobot web channel 正在运行");
    };

    websocket.onclose = (event) => {
      if (cancelled) {
        return;
      }

      setConnectionStatus("disconnected");
      if (event.code !== 1000) {
        onErrorRef.current("WebSocket 连接已断开，请刷新页面后重试");
      }
    };

    return () => {
      cancelled = true;
      websocket.close(1000);
      websocketRef.current = null;
    };
  }, [enabled]);

  function send(
    sessionId: string,
    content: string,
    attachments: Array<ChatAttachment | DraftAttachment> = []
  ) {
    const websocket = websocketRef.current;

    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
      setConnectionStatus("disconnected");
      return false;
    }

    try {
      websocket.send(serializeClientMessage(sessionId, content, attachments));
      return true;
    } catch {
      setConnectionStatus("disconnected");
      return false;
    }
  }

  return {
    connectionStatus,
    send
  };
}
