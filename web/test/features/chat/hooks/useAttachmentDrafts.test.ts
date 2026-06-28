import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CHAT_DRAFTS_STORAGE_KEY,
  useAttachmentDrafts
} from "@/features/chat/hooks/useAttachmentDrafts";
import { validateAttachments } from "@/features/chat/services/chatApi";

vi.mock("@/features/chat/services/chatApi", () => ({
  validateAttachments: vi.fn().mockResolvedValue({ valid: [], invalid: [] })
}));

const readyAttachment = {
  fileId: "att_one",
  fileName: "notes.txt",
  mimeType: "text/plain",
  extension: "txt",
  size: 5,
  kind: "text" as const,
  status: "ready" as const
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useAttachmentDrafts", () => {
  it("saves and restores drafts per session", async () => {
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => useAttachmentDrafts(sessionId),
      { initialProps: { sessionId: "session-a" } }
    );

    act(() => {
      result.current.setInputValue("hello a");
      result.current.setDraftAttachments([readyAttachment]);
    });

    rerender({ sessionId: "session-b" });
    act(() => {
      result.current.setInputValue("hello b");
    });

    rerender({ sessionId: "session-a" });

    await waitFor(() => {
      expect(result.current.inputValue).toBe("hello a");
    });
    expect(result.current.draftAttachments).toEqual([readyAttachment]);
  });

  it("does not persist uploading attachments", () => {
    const { result } = renderHook(() => useAttachmentDrafts("session-a"));

    act(() => {
      result.current.setDraftAttachments([{ ...readyAttachment, fileId: "uploading-one", status: "uploading" }]);
    });

    expect(window.localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY)).toBeNull();
  });

  it("removes invalid restored attachments after validation", async () => {
    window.localStorage.setItem(
      CHAT_DRAFTS_STORAGE_KEY,
      JSON.stringify({
        "session-a": {
          inputValue: "hello",
          attachments: [
            readyAttachment,
            { ...readyAttachment, fileId: "att_missing", fileName: "missing.txt" }
          ]
        }
      })
    );
    vi.mocked(validateAttachments).mockResolvedValue({
      valid: [readyAttachment],
      invalid: ["att_missing"]
    });

    const { result } = renderHook(() => useAttachmentDrafts("session-a"));

    await waitFor(() => {
      expect(result.current.recoveryError).toBe("部分附件已失效，请重新上传");
    });
    expect(result.current.draftAttachments).toEqual([readyAttachment]);
  });

  it("falls back safely when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    const { result } = renderHook(() => useAttachmentDrafts("session-a"));

    expect(result.current.inputValue).toBe("");
    expect(result.current.draftAttachments).toEqual([]);
  });
});
