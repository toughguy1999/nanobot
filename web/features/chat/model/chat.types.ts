export type ChatRole = "user" | "assistant";

export type AttachmentType = "image" | "text";

export type AttachmentStatus = "uploading" | "ready";

export type ChatAttachment = {
  fileId: string;
  fileName: string;
  mimeType: string;
  extension: string;
  size: number;
  type: AttachmentType;
  status?: AttachmentStatus;
  uploadedAt?: string;
};

export type DraftAttachment = ChatAttachment & {
  status: AttachmentStatus;
};

export type ChatMessageMetadata = Record<string, unknown> & {
  attachments?: ChatAttachment[];
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  metadata?: ChatMessageMetadata;
};

export type SessionSummary = {
  id: string;
  key?: string;
  sessionTitle?: string | null;
  createdAt: string;
  updatedAt: string;
  pinned?: boolean;
};

export type Session = SessionSummary & {
  messages: ChatMessage[];
};

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type AssistantMessageEvent = {
  sessionId: string;
  content: string;
};

export type ServerMessage = AssistantMessageEvent | { error: string };
