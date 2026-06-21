import type { ChatMessage, ChatRole, Session } from "@/lib/types";

export function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createSession(): Session {
  const now = new Date().toISOString();

  return {
    id: createId("session"),
    createdAt: now,
    updatedAt: now,
    messages: []
  };
}

export function createMessage(role: ChatRole, content: string): ChatMessage {
  return {
    id: createId("message"),
    role,
    content,
    createdAt: new Date().toISOString()
  };
}

export function appendMessageToSession(
  sessions: Session[],
  sessionId: string,
  message: ChatMessage
) {
  return sessions.map((session) => {
    if (session.id !== sessionId) {
      return session;
    }

    return {
      ...session,
      sessionTitle:
        message.role === "user" && !session.sessionTitle ? message.content : session.sessionTitle,
      updatedAt: message.createdAt,
      messages: [...session.messages, message]
    };
  });
}

export function getSessionTitle(session: Session) {
  if (session.sessionTitle) {
    return session.sessionTitle.length > 28
      ? `${session.sessionTitle.slice(0, 28)}...`
      : session.sessionTitle;
  }

  const firstUserMessage = session.messages.find((message) => message.role === "user");

  if (!firstUserMessage) {
    return "新会话";
  }

  return firstUserMessage.content.length > 28
    ? `${firstUserMessage.content.slice(0, 28)}...`
    : firstUserMessage.content;
}
