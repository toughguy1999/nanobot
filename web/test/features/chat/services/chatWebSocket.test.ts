import { describe, expect, it } from "vitest";
import { serializeClientMessage } from "@/features/chat/services/chatWebSocket";

describe("chatWebSocket", () => {
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
            kind: "text",
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
});
