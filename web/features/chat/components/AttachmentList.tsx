import { FileImage, FileText, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatAttachmentSize } from "../model/attachments";
import type { ChatAttachment, DraftAttachment } from "../model/chat.types";

type AttachmentListProps = {
  attachments: Array<ChatAttachment | DraftAttachment>;
  className?: string;
  onRemove?: (fileId: string) => void;
  variant?: "message" | "composer";
};

export function AttachmentList({
  attachments,
  className,
  onRemove,
  variant = "message"
}: AttachmentListProps) {
  if (attachments.length === 0) {
    return null;
  }

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {attachments.map((attachment) => {
        const Icon = attachment.type === "image" ? FileImage : FileText;
        const isUploading = attachment.status === "uploading";

        return (
          <div
            key={attachment.fileId}
            className={cn(
              "flex h-9 max-w-full items-center gap-2 px-2 text-xs text-foreground shadow-sm",
              variant === "composer"
                ? "rounded-[20px] border bg-[hsl(var(--surface))] shadow-md shadow-[hsl(var(--shadow)/0.12)]"
                : "rounded-md border bg-[hsl(var(--surface))]"
            )}
          >
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="max-w-40 truncate font-medium">{attachment.fileName}</span>
            <span className="shrink-0 text-muted-foreground">
              {isUploading ? "上传中" : formatAttachmentSize(attachment.size)}
            </span>
            {isUploading ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />
            ) : null}
            {onRemove ? (
              <Button
                aria-label={`移除附件 ${attachment.fileName}`}
                className="h-6 w-6 shrink-0"
                size="icon"
                type="button"
                variant="ghost"
                onClick={() => onRemove(attachment.fileId)}
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
