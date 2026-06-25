import { AlertCircle, X } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type ErrorBannerProps = {
  message: string | null;
  onDismiss: () => void;
};

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  if (!message) {
    return null;
  }

  return (
    <Alert variant="destructive" className="flex items-start gap-3">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 break-words">{message}</div>
      <Button
        aria-label="关闭错误提示"
        className="-mr-2 -mt-2 text-destructive hover:bg-destructive/10"
        size="icon"
        variant="ghost"
        onClick={onDismiss}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </Button>
    </Alert>
  );
}
