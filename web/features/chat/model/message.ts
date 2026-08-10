import type { ChatAttachment, ChatMessage, ChatMessageMetadata, ChatRole } from "./chat.types";

export function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createMessage(
  role: ChatRole,
  content: string,
  metadata?: ChatMessageMetadata,
  attachments?: ChatAttachment[]
): ChatMessage {
  return {
    id: createId("message"),
    role,
    content,
    createdAt: new Date().toISOString(),
    ...(attachments && attachments.length > 0 ? { attachments } : {}),
    ...(metadata ? { metadata } : {})
  };
}

export function mergeChatMessage(current: ChatMessage, incoming: ChatMessage): ChatMessage {
  return {
    ...current,
    ...incoming,
    ...(incoming.attachments ?? current.attachments
      ? { attachments: incoming.attachments ?? current.attachments }
      : {}),
    ...(incoming.metadata ?? current.metadata
      ? { metadata: incoming.metadata ?? current.metadata }
      : {}),
    ...(incoming.reasoningContent ?? current.reasoningContent
      ? { reasoningContent: incoming.reasoningContent ?? current.reasoningContent }
      : {}),
    ...(incoming.toolCalls ?? current.toolCalls
      ? { toolCalls: incoming.toolCalls ?? current.toolCalls }
      : {})
  };
}
