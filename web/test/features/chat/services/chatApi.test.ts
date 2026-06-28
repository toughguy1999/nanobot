import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError, uploadAttachment, validateAttachments } from "@/features/chat/services/chatApi";

const attachment = {
  fileId: "att_one",
  fileName: "notes.txt",
  mimeType: "text/plain",
  extension: "txt",
  size: 5,
  kind: "text" as const
};

describe("chatApi attachments", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uploads a multipart attachment", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ attachment })
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await uploadAttachment(
      "session-one",
      new File(["hello"], "notes.txt", { type: "text/plain" })
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8765/attachments",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData)
      })
    );
    expect(result).toEqual({ ...attachment, status: "ready" });
  });

  it("validates attachment ids", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ valid: [attachment], invalid: ["att_missing"] })
      })
    );

    await expect(validateAttachments("session-one", ["att_one", "att_missing"])).resolves.toEqual({
      valid: [{ ...attachment, status: "ready" }],
      invalid: ["att_missing"]
    });
  });

  it("throws HttpError on upload failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400
      })
    );

    await expect(
      uploadAttachment("session-one", new File(["bad"], "bad.pdf"))
    ).rejects.toBeInstanceOf(HttpError);
  });
});
