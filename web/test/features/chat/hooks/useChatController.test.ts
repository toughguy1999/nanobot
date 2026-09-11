import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChatController } from "@/features/chat/hooks/useChatController";
import type { Session } from "@/features/chat/model/chat.types";

const mocks = vi.hoisted(() => ({
  send: vi.fn<(sessionId: string, content: string, attachments: unknown[], messageId: string) => boolean>(() => true),
  uploadAttachment: vi.fn(),
  createRemoteSession: vi.fn(),
  checkServerStatus: vi.fn(),
  fetchSessions: vi.fn(),
  fetchSessionMessages: vi.fn(),
  deleteRemoteSession: vi.fn(),
  pinSession: vi.fn(),
  unpinSession: vi.fn(),
  onSocketMessage: vi.fn()
}));

vi.mock("@/features/chat/hooks/useChatWebSocket", () => ({
  useChatWebSocket: (options: { onMessage: (message: unknown) => void }) => {
    mocks.onSocketMessage.mockImplementation(options.onMessage);
    return {
      connectionStatus: "connected",
      send: mocks.send
    };
  }
}));

vi.mock("@/features/chat/services/chatApi", () => ({
  HttpError: class HttpError extends Error {
    constructor(message: string, public status: number) {
      super(message);
    }
  },
  checkServerStatus: mocks.checkServerStatus,
  createRemoteSession: mocks.createRemoteSession,
  deleteRemoteSession: mocks.deleteRemoteSession,
  fetchSessionMessages: mocks.fetchSessionMessages,
  fetchSessions: mocks.fetchSessions,
  pinSession: mocks.pinSession,
  unpinSession: mocks.unpinSession,
  uploadAttachment: mocks.uploadAttachment,
  validateAttachments: vi.fn().mockResolvedValue({ valid: [], invalid: [] })
}));

const uploadedAttachment = {
  fileId: "att_one",
  fileName: "notes.txt",
  mimeType: "text/plain",
  extension: "txt",
  size: 5,
  type: "text" as const,
  status: "ready" as const
};

describe("useChatController attachments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.checkServerStatus.mockResolvedValue(undefined);
    mocks.fetchSessions.mockResolvedValue([]);
    mocks.createRemoteSession.mockImplementation((sessionId: string) =>
      Promise.resolve({
        id: sessionId,
        key: `web:${sessionId}`,
        createdAt: "2026-06-26T00:00:00.000Z",
        updatedAt: "2026-06-26T00:00:00.000Z",
        messages: []
      })
    );
    mocks.uploadAttachment.mockResolvedValue(uploadedAttachment);
    mocks.send.mockReturnValue(true);
  });

  it("sends a ready attachment without text and clears the draft", async () => {
    const { result } = renderHook(() => useChatController());

    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());

    await act(async () => {
      result.current.actions.addFiles([new File(["hello"], "notes.txt", { type: "text/plain" })]);
    });
    await waitFor(() => expect(result.current.draftAttachments[0]?.status).toBe("ready"));

    expect(mocks.uploadAttachment).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(File)
    );

    await act(async () => {
      await result.current.actions.sendMessage();
    });

    expect(mocks.send).toHaveBeenCalledWith(
      expect.any(String),
      "",
      [expect.objectContaining({ fileId: "att_one" })],
      result.current.activeSession?.messages[0].id
    );
    expect(result.current.draftAttachments).toEqual([]);
  });

  it("keeps each user turn once after switching away and back, including identical text", async () => {
    const { result } = renderHook(() => useChatController());
    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());

    for (let index = 0; index < 2; index += 1) {
      act(() => result.current.actions.setInputValue("same text"));
      await act(async () => { await result.current.actions.sendMessage(); });
    }
    const original = result.current.activeSession!;
    const sentIds = mocks.send.mock.calls.map((args) => args[3]);
    expect(sentIds).toEqual(original.messages.map((message) => message.id));
    expect(new Set(sentIds).size).toBe(2);

    const history: Session = {
      ...original,
      messages: original.messages.flatMap((message, index) => [
        { ...message, id: sentIds[index] },
        { id: `answer-${index}`, role: "assistant", content: "answer", createdAt: message.createdAt }
      ])
    };
    mocks.fetchSessionMessages.mockResolvedValue(history);
    for (let index = 0; index < 2; index += 1) {
      act(() => result.current.actions.createSession());
      await act(async () => { await result.current.actions.selectSession(original.id); });
      expect(result.current.activeSession?.messages).toEqual(history.messages);
    }

    let resolveHistory!: (value: Session) => void;
    mocks.fetchSessionMessages.mockImplementationOnce(() => new Promise<Session>((resolve) => {
      resolveHistory = resolve;
    }));
    let selection!: Promise<void>;
    act(() => { selection = result.current.actions.selectSession(original.id); });
    act(() => result.current.actions.setInputValue("pending"));
    await act(async () => { await result.current.actions.sendMessage(); });
    const pending = result.current.activeSession!.messages.at(-1)!;
    await act(async () => {
      resolveHistory(history);
      await selection;
    });
    expect(result.current.activeSession?.messages).toEqual([...history.messages, pending]);
  });

  it("does not send while an attachment is uploading", async () => {
    mocks.uploadAttachment.mockImplementation(() => new Promise(() => undefined));
    const { result } = renderHook(() => useChatController());

    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());
    act(() => {
      result.current.actions.addFiles([new File(["hello"], "notes.txt", { type: "text/plain" })]);
    });

    expect(result.current.isUploadingAttachments).toBe(true);
    await act(async () => {
      await result.current.actions.sendMessage();
    });

    expect(mocks.send).not.toHaveBeenCalled();
  });

  it("keeps text and ready attachments when websocket send fails", async () => {
    mocks.send.mockReturnValue(false);
    const { result } = renderHook(() => useChatController());

    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());
    act(() => {
      result.current.actions.setInputValue("hello");
    });
    await act(async () => {
      result.current.actions.addFiles([new File(["hello"], "notes.txt", { type: "text/plain" })]);
    });
    await waitFor(() => expect(result.current.draftAttachments[0]?.status).toBe("ready"));

    await act(async () => {
      await result.current.actions.sendMessage();
    });

    expect(result.current.inputValue).toBe("hello");
    expect(result.current.draftAttachments).toHaveLength(1);
    expect(result.current.activeSession?.messages).toEqual([]);
  });

  it("merges duplicate server events into the declared non-active session", async () => {
    mocks.fetchSessions.mockResolvedValue([
      {
        id: "one",
        key: "web:one",
        createdAt: "2026-08-08T09:00:00",
        updatedAt: "2026-08-08T09:00:00",
        messages: []
      },
      {
        id: "two",
        key: "web:two",
        createdAt: "2026-08-08T09:00:00",
        updatedAt: "2026-08-08T09:00:00",
        messages: []
      }
    ]);
    mocks.fetchSessionMessages.mockResolvedValue({
      id: "one",
      key: "web:one",
      createdAt: "2026-08-08T09:00:00",
      updatedAt: "2026-08-08T09:00:00",
      messages: []
    });
    const { result } = renderHook(() => useChatController());
    await waitFor(() => expect(result.current.activeSessionId).toBe("one"));
    const stage = {
      type: "assistant_stage",
      sessionId: "two",
      message: {
        id: "msg-a1",
        role: "assistant",
        content: "",
        reasoningContent: "thinking",
        toolCalls: [{ id: "call-1", name: "search", arguments: "{}" }],
        createdAt: "2026-08-08T10:00:00"
      }
    };

    act(() => {
      mocks.onSocketMessage(stage);
      mocks.onSocketMessage(stage);
      mocks.onSocketMessage({
        ...stage,
        type: "assistant_final",
        message: { ...stage.message, content: "answer" }
      });
    });

    expect(result.current.activeSessionId).toBe("one");
    expect(result.current.sessions.find((session) => session.id === "one")?.messages).toEqual([]);
    expect(result.current.sessions.find((session) => session.id === "two")?.messages).toEqual([
      { ...stage.message, content: "answer" }
    ]);
  });
});
