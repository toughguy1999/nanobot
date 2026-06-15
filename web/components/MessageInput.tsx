import { FormEvent } from "react";
import { SendHorizonal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

type MessageInputProps = {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
};

export function MessageInput({ value, disabled, onChange, onSend }: MessageInputProps) {
  const canSend = value.trim().length > 0 && !disabled;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (canSend) {
      onSend();
    }
  }

  return (
    <form className="border-t bg-white px-6 py-4" onSubmit={handleSubmit}>
      <div className="mx-auto flex max-w-3xl items-end gap-3">
        <Textarea
          aria-label="消息内容"
          className="min-h-14 flex-1"
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
        <Button aria-label="发送消息" disabled={!canSend} size="icon" type="submit">
          <SendHorizonal className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </form>
  );
}
