import type { ChatMessage } from "../model/chat.types";
import { MarkdownContent } from "./MarkdownContent";
import { ProcessBlock } from "./ProcessBlock";

type AssistantMessageProps = {
  message: ChatMessage;
};

export function AssistantMessage({ message }: AssistantMessageProps) {
  const hasToolCalls = Boolean(message.toolCalls?.length);
  const hasProcess = Boolean(message.reasoningContent || hasToolCalls);
  const content = hasToolCalls ? `*正在调用工具🔧...*\n\n${message.content}` : message.content

  return (
    <>
      {hasProcess ? (
        <ProcessBlock
          reasoningContent={message.reasoningContent}
          toolCalls={message.toolCalls}
        />
      ) : null}
      <MarkdownContent content={content} variant="assistant" />
    </>
  );
}
