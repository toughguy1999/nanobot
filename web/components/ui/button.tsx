import * as React from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "default" | "secondary" | "ghost" | "destructive";
type ButtonSize = "default" | "icon";

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const variantClasses: Record<ButtonVariant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-[hsl(var(--surface-subtle))] text-foreground hover:bg-muted",
  ghost: "hover:bg-[hsl(var(--surface-subtle))]",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90"
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-10 px-4 py-2",
  icon: "h-10 w-10"
};

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    />
  )
);

Button.displayName = "Button";

export { Button };
