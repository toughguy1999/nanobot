import type { ChatMessage, Session, SessionSummary } from "@/lib/types";

export const DEFAULT_HTTP_URL = "http://localhost:8765";

type SessionListResponse = {
  sessions: SessionSummary[];
};

type SessionResponse = {
  session: SessionSummary;
};

type SessionDetailResponse = {
  session: SessionSummary;
  messages: ChatMessage[];
};

function assertOk(response: Response, message: string) {
  if (!response.ok) {
    throw new Error(`${message}：${response.status}`);
  }
}

export function getHttpUrl() {
  return (process.env.NEXT_PUBLIC_NANOBOT_HTTP_URL ?? DEFAULT_HTTP_URL).replace(/\/$/, "");
}

export async function checkServerStatus() {
  const response = await fetch(`${getHttpUrl()}/status`, {
    cache: "no-store"
  });
  assertOk(response, "服务端状态检查失败");
}

export async function fetchSessions(): Promise<Session[]> {
  const response = await fetch(`${getHttpUrl()}/sessions`, {
    cache: "no-store"
  });
  assertOk(response, "获取历史会话失败");

  const data = (await response.json()) as SessionListResponse;
  return data.sessions.map((session) => ({
    ...session,
    messages: []
  }));
}

export async function createRemoteSession(sessionId: string): Promise<Session> {
  const response = await fetch(`${getHttpUrl()}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ sessionId })
  });
  assertOk(response, "创建会话失败");

  const data = (await response.json()) as SessionResponse;
  return {
    ...data.session,
    messages: []
  };
}

export async function fetchSessionMessages(sessionId: string): Promise<Session> {
  const response = await fetch(`${getHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/messages`, {
    cache: "no-store"
  });
  assertOk(response, "获取历史消息失败");

  const data = (await response.json()) as SessionDetailResponse;
  return {
    ...data.session,
    messages: data.messages
  };
}
