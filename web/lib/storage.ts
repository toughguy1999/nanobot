import type { Session } from "@/lib/types";

const SESSIONS_KEY = "nanobot.web.sessions";
const ACTIVE_SESSION_KEY = "nanobot.web.activeSessionId";

function canUseStorage() {
  return typeof window !== "undefined" && "localStorage" in window;
}

export function loadSessions(): Session[] {
  if (!canUseStorage()) {
    return [];
  }

  try {
    const rawValue = window.localStorage.getItem(SESSIONS_KEY);
    if (!rawValue) {
      return [];
    }

    const sessions = JSON.parse(rawValue);
    return Array.isArray(sessions) ? sessions : [];
  } catch {
    return [];
  }
}

export function saveSessions(sessions: Session[]) {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function loadActiveSessionId() {
  if (!canUseStorage()) {
    return null;
  }

  return window.localStorage.getItem(ACTIVE_SESSION_KEY);
}

export function saveActiveSessionId(sessionId: string | null) {
  if (!canUseStorage()) {
    return;
  }

  if (!sessionId) {
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
    return;
  }

  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
}
