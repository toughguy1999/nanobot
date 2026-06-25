"use client";

import { useChatController } from "../hooks/useChatController";
import { ChatHeader } from "./ChatHeader";
import { ConversationView } from "./ConversationView";
import { ErrorBanner } from "./ErrorBanner";
import { MessageInput } from "./MessageInput";
import { Sidebar } from "./Sidebar";

export function ChatPage() {
  const controller = useChatController();

  return (
    <main className="flex h-screen min-h-screen overflow-hidden bg-background">
      <Sidebar
        activeSessionId={controller.activeSessionId}
        sessions={controller.sessions}
        onCreateSession={controller.actions.createSession}
        onDeleteSession={controller.actions.deleteSession}
        onPinSession={controller.actions.pinSession}
        onSelectSession={controller.actions.selectSession}
        onUnpinSession={controller.actions.unpinSession}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          activeSession={controller.activeSession}
          connectionStatus={controller.connectionStatus}
        />

        <div className="shrink-0 px-6 pt-4">
          <ErrorBanner
            message={controller.errorMessage}
            onDismiss={controller.actions.dismissError}
          />
        </div>

        <ConversationView session={controller.activeSession} />

        <MessageInput
          disabled={controller.inputDisabled}
          value={controller.inputValue}
          onChange={controller.actions.setInputValue}
          onSend={controller.actions.sendMessage}
        />
      </section>
    </main>
  );
}
