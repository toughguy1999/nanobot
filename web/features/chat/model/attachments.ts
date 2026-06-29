import type { AttachmentType, ChatAttachment, DraftAttachment } from "./chat.types";

export const MAX_ATTACHMENTS_PER_MESSAGE = 5;
export const MAX_SINGLE_ATTACHMENT_SIZE = 10 * 1024 * 1024;
export const MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024;
export const DEFAULT_ATTACHMENT_PROMPT = "请查看我上传的文件。";

export const IMAGE_ATTACHMENT_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "bmp"];
export const TEXT_ATTACHMENT_EXTENSIONS = [
  "txt",
  "md",
  "markdown",
  "json",
  "csv",
  "tsv",
  "yaml",
  "yml",
  "log"
];
export const SUPPORTED_ATTACHMENT_EXTENSIONS = [
  ...IMAGE_ATTACHMENT_EXTENSIONS,
  ...TEXT_ATTACHMENT_EXTENSIONS
];

export function getAttachmentExtension(fileName: string) {
  const extension = fileName.split(".").pop()?.toLowerCase() ?? "";
  return extension === fileName.toLowerCase() ? "" : extension;
}

export function getAttachmentType(extension: string): AttachmentType | null {
  if (IMAGE_ATTACHMENT_EXTENSIONS.includes(extension)) {
    return "image";
  }
  if (TEXT_ATTACHMENT_EXTENSIONS.includes(extension)) {
    return "text";
  }
  return null;
}

export function formatAttachmentSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateFilesForAttachmentDraft(
  files: File[],
  currentAttachments: DraftAttachment[]
) {
  if (currentAttachments.length + files.length > MAX_ATTACHMENTS_PER_MESSAGE) {
    return `最多只能添加 ${MAX_ATTACHMENTS_PER_MESSAGE} 个附件`;
  }

  const existingSize = currentAttachments.reduce((total, attachment) => total + attachment.size, 0);
  const incomingSize = files.reduce((total, file) => total + file.size, 0);
  if (existingSize + incomingSize > MAX_TOTAL_ATTACHMENT_SIZE) {
    return "附件总大小不能超过 25 MB";
  }

  for (const file of files) {
    const extension = getAttachmentExtension(file.name);
    if (!getAttachmentType(extension)) {
      return "不支持该文件类型";
    }
    if (file.size > MAX_SINGLE_ATTACHMENT_SIZE) {
      return "单个附件不能超过 10 MB";
    }
  }

  return null;
}

export function createUploadingAttachment(file: File): DraftAttachment {
  const extension = getAttachmentExtension(file.name);
  const type = getAttachmentType(extension) ?? "text";
  const randomPart =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return {
    fileId: `uploading-${randomPart}`,
    fileName: file.name,
    mimeType: file.type,
    extension,
    size: file.size,
    type,
    status: "uploading"
  };
}

export function toReadyDraftAttachment(attachment: ChatAttachment): DraftAttachment {
  return {
    ...attachment,
    status: "ready"
  };
}
