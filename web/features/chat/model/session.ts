import type { ChatMessage, Session } from "./chat.types";
import { createId } from "./message";

export function createSession(): Session {
  const now = new Date().toISOString();

  return {
    id: createId("session"),
    createdAt: now,
    updatedAt: now,
    pinned: false,
    messages: []
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

export function sortSessions(sessions: Session[]) {
  return [...sessions].sort((a, b) => {
    if (Boolean(a.pinned) !== Boolean(b.pinned)) {
      return Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
    }

    return b.updatedAt.localeCompare(a.updatedAt);
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

export function mergeSessionSummary(currentSessions: Session[], updatedSession: Session) {
  return sortSessions(
    currentSessions.map((session) =>
      session.id === updatedSession.id
        ? {
            ...updatedSession,
            messages: session.messages
          }
        : session
    )
  );
}

export function removeSessionAndSelectNext(
  currentSessions: Session[],
  removedSessionId: string,
  currentActiveSessionId: string | null
) {
  const remainingSessions = sortSessions(
    currentSessions.filter((session) => session.id !== removedSessionId)
  );

  if (currentActiveSessionId !== removedSessionId) {
    return {
      sessions: remainingSessions,
      activeSessionId: currentActiveSessionId
    };
  }

  if (remainingSessions.length > 0) {
    return {
      sessions: remainingSessions,
      activeSessionId: remainingSessions[0].id
    };
  }

  const emptySession = createSession();
  return {
    sessions: [emptySession],
    activeSessionId: emptySession.id
  };
}
