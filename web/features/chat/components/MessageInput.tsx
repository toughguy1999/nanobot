import { ChangeEvent, FormEvent, useRef } from "react";
import { Paperclip, SendHorizonal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SUPPORTED_ATTACHMENT_EXTENSIONS } from "../model/attachments";
import type { DraftAttachment } from "../model/chat.types";
import { AttachmentList } from "./AttachmentList";

type MessageInputProps = {
  value: string;
  disabled: boolean;
  attachments: DraftAttachment[];
  isUploadingAttachments: boolean;
  onChange: (value: string) => void;
  onAddFiles: (files: File[]) => void;
  onRemoveAttachment: (fileId: string) => void;
  onSend: () => void;
};

export function MessageInput({
  value,
  disabled,
  attachments,
  isUploadingAttachments,
  onChange,
  onAddFiles,
  onRemoveAttachment,
  onSend
}: MessageInputProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const hasReadyAttachment = attachments.some((attachment) => attachment.status === "ready");
  const canSend = (value.trim().length > 0 || hasReadyAttachment) && !disabled && !isUploadingAttachments;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (canSend) {
      onSend();
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length > 0) {
      onAddFiles(files);
    }
    event.target.value = "";
  }

  return (
    <form className="border-t bg-white px-6 py-4" onSubmit={handleSubmit}>
      <div className="mx-auto flex max-w-3xl flex-col rounded-md border bg-white px-3 py-2 shadow-sm">
        <AttachmentList
          attachments={attachments}
          className={attachments.length > 0 ? "pb-2" : ""}
          onRemove={onRemoveAttachment}
        />
        <Textarea
          aria-label="消息内容"
          className="min-h-16 border-0 px-0 shadow-none focus-visible:ring-0"
          disabled={disabled}
          placeholder="输入消息..."
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (canSend) {
                onSend();
              }
            }
          }}
        />
        <div className="flex items-center justify-between pt-2">
          <input
            ref={inputRef}
            className="hidden"
            type="file"
            multiple
            accept={SUPPORTED_ATTACHMENT_EXTENSIONS.map((extension) => `.${extension}`).join(",")}
            onChange={handleFileChange}
          />
          <Button
            aria-label="添加附件"
            disabled={disabled}
            size="icon"
            type="button"
            variant="ghost"
            onClick={() => inputRef.current?.click()}
          >
            <Paperclip className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button aria-label="发送消息" disabled={!canSend} size="icon" type="submit">
            <SendHorizonal className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </form>
  );
}
