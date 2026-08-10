"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ToolCallView } from "../model/chat.types";
import { MarkdownContent } from "./MarkdownContent";
import { ToolCallList } from "./ToolCallList";

type ProcessBlockProps = {
  reasoningContent?: string;
  toolCalls?: ToolCallView[];
};

export function ProcessBlock({ reasoningContent, toolCalls = [] }: ProcessBlockProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="mb-3 overflow-hidden rounded-md border bg-[hsl(var(--surface-subtle))]">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs font-medium text-muted-foreground"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>思考过程</span>
        <ChevronDown
          className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      {expanded ? (
        <div className="space-y-3 border-t px-3 py-3 text-sm">
          {reasoningContent ? (
            <MarkdownContent content={reasoningContent} variant="process" />
          ) : null}
          {toolCalls.length > 0 ? <ToolCallList toolCalls={toolCalls} /> : null}
        </div>
      ) : null}
    </section>
  );
}
