import type { ChatMessage, ChatRole } from "./chat.types";

export function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createMessage(role: ChatRole, content: string): ChatMessage {
  return {
    id: createId("message"),
    role,
    content,
    createdAt: new Date().toISOString()
  };
}
