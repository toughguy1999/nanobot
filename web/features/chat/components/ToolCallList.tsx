import type { ToolCallView } from "../model/chat.types";

type ToolCallListProps = {
  toolCalls: ToolCallView[];
};

export function ToolCallList({ toolCalls }: ToolCallListProps) {
  return (
    <ol className="space-y-3" aria-label="工具调用">
      {toolCalls.map((toolCall) => (
        <li key={toolCall.id} className="min-w-0">
          <div className="mb-1 font-medium text-foreground">{toolCall.name}</div>
          <pre className="max-w-full overflow-x-auto whitespace-pre rounded-md bg-black/10 p-3 text-xs text-foreground">
            <code>{formatArguments(toolCall.arguments)}</code>
          </pre>
        </li>
      ))}
    </ol>
  );
}

function formatArguments(argumentsValue: string) {
  try {
    return JSON.stringify(JSON.parse(argumentsValue), null, 2);
  } catch {
    return argumentsValue;
  }
}
