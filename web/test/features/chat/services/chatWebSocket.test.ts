import { describe, expect, it } from "vitest";
import {
  parseServerMessage,
  serializeClientMessage
} from "@/features/chat/services/chatWebSocket";

describe("chatWebSocket", () => {
  it("includes the optimistic user message id in the wire payload", () => {
    expect(JSON.parse(serializeClientMessage("one", "hello", [], "message-local"))).toEqual({
      sessionId: "one",
      content: "hello",
      messageId: "message-local"
    });
  });

  it("serializes plain text messages without attachments for compatibility", () => {
    expect(JSON.parse(serializeClientMessage("session-one", "hello"))).toEqual({
      sessionId: "session-one",
      content: "hello"
    });
  });

  it("serializes only attachment fileIds", () => {
    expect(
      JSON.parse(
        serializeClientMessage("session-one", "hello", [
          {
            fileId: "att_one",
            fileName: "secret.txt",
            mimeType: "text/plain",
            extension: "txt",
            size: 5,
            type: "text",
            status: "ready"
          }
        ])
      )
    ).toEqual({
      sessionId: "session-one",
      content: "hello",
      attachments: [{ fileId: "att_one" }]
    });
  });

  it("strictly parses assistant stage and final events", () => {
    const message = {
      id: "msg-a1",
      role: "assistant",
      content: "",
      reasoningContent: "thinking",
      toolCalls: [{ id: "call-1", name: "search", arguments: '{ "q": 1 }' }],
      createdAt: "2026-08-08T10:00:00"
    };

    expect(
      parseServerMessage(
        JSON.stringify({ type: "assistant_stage", sessionId: "one", message })
      )
    ).toEqual({ type: "assistant_stage", sessionId: "one", message });
    expect(
      parseServerMessage(
        JSON.stringify({
          type: "assistant_final",
          sessionId: "one",
          message: { ...message, content: "answer", toolCalls: undefined }
        })
      )
    ).toEqual({
      type: "assistant_final",
      sessionId: "one",
      message: { ...message, content: "answer", toolCalls: undefined }
    });
  });

  it("routes malformed and unknown typed payloads to the error result", () => {
    expect(
      parseServerMessage(
        JSON.stringify({
          type: "assistant_stage",
          sessionId: "one",
          message: { id: "msg-a1", content: "missing fields" }
        })
      )
    ).toEqual({ error: "服务端返回了无法识别的消息" });
    expect(
      parseServerMessage(
        JSON.stringify({ type: "unknown", sessionId: "one", content: "do not accept" })
      )
    ).toEqual({ error: "服务端返回了无法识别的消息" });
  });
});
