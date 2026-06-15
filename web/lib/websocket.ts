import type { ServerMessage } from "@/lib/types";

export const DEFAULT_HTTP_URL = "http://localhost:8765";
export const DEFAULT_WS_URL = "ws://localhost:8765/ws";

export function getHttpUrl() {
  return (process.env.NEXT_PUBLIC_NANOBOT_HTTP_URL ?? DEFAULT_HTTP_URL).replace(/\/$/, "");
}

export function getWebSocketUrl() {
  return process.env.NEXT_PUBLIC_NANOBOT_WS_URL ?? DEFAULT_WS_URL;
}

export async function checkServerStatus() {
  const response = await fetch(`${getHttpUrl()}/status`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`服务端状态检查失败：${response.status}`);
  }
}

export function parseServerMessage(rawValue: string): ServerMessage {
  const data = JSON.parse(rawValue) as unknown;

  if (!data || typeof data !== "object") {
    return { error: "服务端返回了无效消息" };
  }

  if ("error" in data && typeof data.error === "string") {
    return { error: data.error };
  }

  if ("content" in data && typeof data.content === "string") {
    return { content: data.content };
  }

  return { error: "服务端返回了无法识别的消息" };
}
