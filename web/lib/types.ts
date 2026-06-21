export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  metadata?: Record<string, unknown>;
};

export type SessionSummary = {
  id: string;
  key?: string;
  sessionTitle?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Session = SessionSummary & {
  messages: ChatMessage[];
};

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type ServerMessage =
  | {
      sessionId: string;
      content: string;
    }
  | {
      error: string;
    };
