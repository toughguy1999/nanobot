import type { ChatAttachment, ChatMessage, Session, SessionSummary } from "../model/chat.types";

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

type AttachmentResponse = {
  attachment: ChatAttachment;
};

type ValidateAttachmentsResponse = {
  valid: ChatAttachment[];
  invalid: string[];
};

export class HttpError extends Error {
  constructor(message: string, public status: number) {
    super(`${message}：${status}`);
  }
}

function assertOk(response: Response, message: string) {
  if (!response.ok) {
    throw new HttpError(message, response.status);
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

export async function pinSession(sessionId: string): Promise<Session> {
  const response = await fetch(`${getHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/pin`, {
    method: "POST"
  });
  assertOk(response, "置顶会话失败");

  const data = (await response.json()) as SessionResponse;
  return {
    ...data.session,
    messages: []
  };
}

export async function unpinSession(sessionId: string): Promise<Session> {
  const response = await fetch(`${getHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/unpin`, {
    method: "POST"
  });
  assertOk(response, "取消置顶会话失败");

  const data = (await response.json()) as SessionResponse;
  return {
    ...data.session,
    messages: []
  };
}

export async function deleteRemoteSession(sessionId: string): Promise<void> {
  const response = await fetch(`${getHttpUrl()}/sessions/${encodeURIComponent(sessionId)}/delete`, {
    method: "POST"
  });
  assertOk(response, "删除会话失败");
}

function normalizeAttachment(attachment: ChatAttachment): ChatAttachment {
  return {
    ...attachment,
    status: "ready"
  };
}

export async function uploadAttachment(sessionId: string, file: File): Promise<ChatAttachment> {
  const formData = new FormData();
  formData.append("sessionId", sessionId);
  formData.append("file", file);

  const response = await fetch(`${getHttpUrl()}/attachments`, {
    method: "POST",
    body: formData
  });
  assertOk(response, "上传附件失败");

  const data = (await response.json()) as AttachmentResponse;
  return normalizeAttachment(data.attachment);
}

export async function validateAttachments(
  sessionId: string,
  fileIds: string[]
): Promise<{ valid: ChatAttachment[]; invalid: string[] }> {
  const response = await fetch(`${getHttpUrl()}/attachments/validate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ sessionId, fileIds })
  });
  assertOk(response, "校验附件失败");

  const data = (await response.json()) as ValidateAttachmentsResponse;
  return {
    valid: data.valid.map(normalizeAttachment),
    invalid: data.invalid
  };
}
