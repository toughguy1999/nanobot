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

export type ChatMessageMetadata = Record<string, unknown>;

export type ToolCallView = {
  id: string;
  name: string;
  arguments: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  attachments?: ChatAttachment[];
  metadata?: ChatMessageMetadata;
  reasoningContent?: string;
  toolCalls?: ToolCallView[];
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

export type ActiveMessageEvent = {
  sessionId: string;
  content: string;
};

export type AssistantStageEvent = {
  type: "assistant_stage";
  sessionId: string;
  message: ChatMessage;
};

export type AssistantFinalEvent = {
  type: "assistant_final";
  sessionId: string;
  message: ChatMessage;
};

export type ChatServerEvent = ActiveMessageEvent | AssistantStageEvent | AssistantFinalEvent;

export type ServerMessage = ChatServerEvent | { error: string };
