import { ChangeEvent, FormEvent, useEffect, useRef } from "react";
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const hasReadyAttachment = attachments.some((attachment) => attachment.status === "ready");
  const canSend = (value.trim().length > 0 || hasReadyAttachment) && !disabled && !isUploadingAttachments;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, 64), 180);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 180 ? "auto" : "hidden";
  }, [value]);

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
    <form className="absolute inset-x-0 bottom-0 z-10 bg-transparent px-6 pb-6 pt-2" onSubmit={handleSubmit}>
      <div className="mx-auto flex max-w-3xl flex-col gap-2">
        <AttachmentList
          attachments={attachments}
          className="px-1"
          onRemove={onRemoveAttachment}
          variant="composer"
        />
        <div className="flex flex-col rounded-[20px] border bg-[hsl(var(--surface))] px-4 py-3 shadow-lg shadow-[hsl(var(--shadow)/0.14)]">
          <Textarea
            ref={textareaRef}
            aria-label="消息内容"
            className="max-h-[180px] min-h-[64px] resize-none border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
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
      </div>
    </form>
  );
}
