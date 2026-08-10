import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

type MarkdownContentProps = {
  content: string;
  variant?: "user" | "assistant" | "process";
};

export function MarkdownContent({
  content,
  variant = "assistant"
}: MarkdownContentProps) {
  return (
    <div
      className={cn(
        "min-w-0 break-words [overflow-wrap:anywhere]",
        variant === "process" && "text-muted-foreground"
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrlTransform}
        components={{
          h1: ({ children }) => <h1 className="mb-3 mt-4 text-xl font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-4 text-lg font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-3 font-semibold">{children}</h3>,
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l-2 border-current/30 pl-3 opacity-90">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="my-3 max-w-full overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border px-2 py-1 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border px-2 py-1 align-top">{children}</td>,
          pre: ({ children }) => (
            <pre className="my-3 max-w-full overflow-x-auto whitespace-pre rounded-md bg-black/10 p-3 text-xs">
              {children}
            </pre>
          ),
          code: ({ children, className }) => (
            <code
              className={cn(
                className,
                !className && "rounded bg-black/10 px-1 py-0.5 font-mono text-[0.9em]"
              )}
            >
              {children}
            </code>
          ),
          a: ({ children, href }) => {
            const external = Boolean(href && /^https?:\/\//i.test(href));
            return (
              <a
                href={href}
                className="font-medium underline decoration-current/40 underline-offset-2"
                {...(external
                  ? { target: "_blank", rel: "noopener noreferrer nofollow" }
                  : { rel: "nofollow" })}
              >
                {children}
              </a>
            );
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function safeUrlTransform(url: string) {
  if (/^(?:https?:|mailto:)/i.test(url) || /^(?:[/.#?]|$)/.test(url)) {
    return defaultUrlTransform(url);
  }
  return "";
}
