import * as React from "react";
import { cn } from "@/lib/utils";

type AlertVariant = "default" | "destructive";

export type AlertProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: AlertVariant;
};

const variantClasses: Record<AlertVariant, string> = {
  default: "border-border bg-background text-foreground",
  destructive: "border-destructive/30 bg-destructive/10 text-destructive"
};

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      className={cn(
        "rounded-md border px-4 py-3 text-sm leading-6",
        variantClasses[variant],
        className
      )}
      {...props}
    />
  )
);

Alert.displayName = "Alert";

export { Alert };
