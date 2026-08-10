import { describe, expect, it } from "vitest";
import type { ChatMessage, Session } from "@/features/chat/model/chat.types";
import {
  mergeLoadedSession,
  sortSessions,
  upsertMessageToSession
} from "@/features/chat/model/session";

const session = (id: string, messages: ChatMessage[] = []): Session => ({
  id,
  createdAt: "2026-08-08T09:00:00",
  updatedAt: "2026-08-08T09:00:00",
  messages
});

const assistant = (id: string, content: string): ChatMessage => ({
  id,
  role: "assistant",
  content,
  createdAt: "2026-08-08T10:00:00"
});

describe("session realtime merging", () => {
  it("upserts by target session and stable server message id", () => {
    const sessions = [session("one"), session("two")];
    const stage = {
      ...assistant("msg-a1", ""),
      reasoningContent: "thinking",
      toolCalls: [{ id: "call-1", name: "search", arguments: "{}" }]
    };

    const once = upsertMessageToSession(sessions, "two", stage);
    const duplicate = upsertMessageToSession(once, "two", stage);
    const updated = upsertMessageToSession(duplicate, "two", assistant("msg-a1", "answer"));

    expect(updated[0].messages).toEqual([]);
    expect(updated[1].messages).toEqual([
      {
        ...stage,
        content: "answer"
      }
    ]);
  });

  it("preserves realtime and optimistic messages during a history load race", () => {
    const existing = session("one", [
      assistant("msg-live", "live"),
      {
        id: "local-user",
        role: "user",
        content: "optimistic",
        createdAt: "2026-08-08T10:00:01"
      }
    ]);
    const loaded = session("one", [assistant("msg-history", "history")]);

    expect(mergeLoadedSession(existing, loaded).messages.map((message) => message.id)).toEqual([
      "msg-history",
      "msg-live",
      "local-user"
    ]);
  });

  it("keeps pinned-first and updated-time sorting", () => {
    expect(
      sortSessions([
        { ...session("new"), updatedAt: "2026-08-08T11:00:00" },
        { ...session("pinned"), pinned: true, updatedAt: "2026-08-08T09:00:00" }
      ]).map((item) => item.id)
    ).toEqual(["pinned", "new"]);
  });
});
