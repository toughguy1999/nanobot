import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationView } from "@/features/chat/components/ConversationView";
import type { Session } from "@/features/chat/model/chat.types";

const attachment = {
  fileId: "att_one",
  fileName: "notes.txt",
  mimeType: "text/plain",
  extension: "txt",
  size: 5,
  type: "text" as const,
  status: "ready" as const
};

function createSession(messages: Session["messages"]): Session {
  return {
    id: "session-one",
    createdAt: "2026-06-26T00:00:00.000Z",
    updatedAt: "2026-06-26T00:00:00.000Z",
    messages
  };
}

describe("ConversationView attachments", () => {
  it("shows user attachments above message text", () => {
    render(
      <ConversationView
        session={createSession([
          {
            id: "message-one",
            role: "user",
            content: "please read",
            createdAt: "2026-06-26T00:00:00.000Z",
            metadata: { attachments: [attachment] }
          }
        ])}
      />
    );

    const attachmentNode = screen.getByText("notes.txt");
    const contentNode = screen.getByText("please read");

    expect(attachmentNode).toBeVisible();
    expect(contentNode).toBeVisible();
    expect(
      attachmentNode.compareDocumentPosition(contentNode) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("does not show assistant attachments", () => {
    render(
      <ConversationView
        session={createSession([
          {
            id: "message-one",
            role: "assistant",
            content: "answer",
            createdAt: "2026-06-26T00:00:00.000Z",
            metadata: { attachments: [attachment] }
          }
        ])}
      />
    );

    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
    expect(screen.getByText("answer")).toBeVisible();
  });

  it("keeps plain messages unchanged", () => {
    render(
      <ConversationView
        session={createSession([
          {
            id: "message-one",
            role: "user",
            content: "plain",
            createdAt: "2026-06-26T00:00:00.000Z"
          }
        ])}
      />
    );

    expect(screen.getByText("plain")).toBeVisible();
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
  });
});
