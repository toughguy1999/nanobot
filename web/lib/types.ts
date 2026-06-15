export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
};

export type Session = {
  id: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type ServerMessage =
  | {
      content: string;
    }
  | {
      error: string;
    };
