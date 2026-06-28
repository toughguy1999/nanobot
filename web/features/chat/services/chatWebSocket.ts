import type { ChatAttachment, DraftAttachment, ServerMessage } from "../model/chat.types";

export const DEFAULT_WS_URL = "ws://localhost:8765/ws";

export function getWebSocketUrl() {
  return process.env.NEXT_PUBLIC_NANOBOT_WS_URL ?? DEFAULT_WS_URL;
}

export function serializeClientMessage(
  sessionId: string,
  content: string,
  attachments: Array<ChatAttachment | DraftAttachment> = []
) {
  const payload: {
    sessionId: string;
    content: string;
    attachments?: { fileId: string }[];
  } = {
    sessionId,
    content
  };

  if (attachments.length > 0) {
    payload.attachments = attachments.map((attachment) => ({ fileId: attachment.fileId }));
  }

  return JSON.stringify(payload);
}

export function parseServerMessage(rawValue: string): ServerMessage {
  const data = JSON.parse(rawValue) as unknown;

  if (!data || typeof data !== "object") {
    return { error: "服务端返回了无效消息" };
  }

  if ("error" in data && typeof data.error === "string") {
    return { error: data.error };
  }

  if (
    "sessionId" in data &&
    typeof data.sessionId === "string" &&
    "content" in data &&
    typeof data.content === "string"
  ) {
    return { sessionId: data.sessionId, content: data.content };
  }

  return { error: "服务端返回了无法识别的消息" };
}
