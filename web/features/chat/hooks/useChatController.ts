"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatServerEvent, Session } from "../model/chat.types";
import {
  createUploadingAttachment,
  DEFAULT_ATTACHMENT_PROMPT,
  toReadyDraftAttachment,
  validateFilesForAttachmentDraft
} from "../model/attachments";
import { createMessage } from "../model/message";
import {
  appendMessageToSession,
  createSession,
  mergeLoadedSession,
  mergeSessionSummary,
  removeSessionAndSelectNext,
  sortSessions,
  upsertMessageToSession
} from "../model/session";
import {
  checkServerStatus,
  createRemoteSession,
  deleteRemoteSession,
  fetchSessionMessages,
  fetchSessions,
  HttpError,
  pinSession,
  uploadAttachment,
  unpinSession
} from "../services/chatApi";
import { useAttachmentDrafts } from "./useAttachmentDrafts";
import { useChatWebSocket } from "./useChatWebSocket";

export function useChatController() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [webSocketEnabled, setWebSocketEnabled] = useState(false);
  const [initializationFailed, setInitializationFailed] = useState(false);
  const sessionsRef = useRef(sessions);
  const activeSessionIdRef = useRef(activeSessionId);

  sessionsRef.current = sessions;
  activeSessionIdRef.current = activeSessionId;

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [activeSessionId, sessions]
  );

  const {
    inputValue,
    draftAttachments,
    recoveryError,
    setInputValue,
    setDraftAttachments,
    clearDraft
  } = useAttachmentDrafts(activeSessionId);

  const readyAttachments = useMemo(
    () => draftAttachments.filter((attachment) => attachment.status === "ready"),
    [draftAttachments]
  );
  const isUploadingAttachments = useMemo(
    () => draftAttachments.some((attachment) => attachment.status === "uploading"),
    [draftAttachments]
  );

  useEffect(() => {
    if (recoveryError) {
      setErrorMessage(recoveryError);
    }
  }, [recoveryError]);

  const handleAssistantMessage = useCallback((event: ChatServerEvent) => {
    setSessions((currentSessions) =>
      sortSessions(
        "type" in event
          ? upsertMessageToSession(currentSessions, event.sessionId, event.message)
          : appendMessageToSession(
              currentSessions,
              event.sessionId,
              createMessage("assistant", event.content)
            )
      )
    );
  }, []);

  const handleWebSocketError = useCallback((message: string) => {
    setErrorMessage(message || null);
  }, []);

  const { connectionStatus, send } = useChatWebSocket({
    enabled: webSocketEnabled,
    onMessage: handleAssistantMessage,
    onError: handleWebSocketError
  });

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      try {
        await checkServerStatus();
        const serverSessions = sortSessions(await fetchSessions());
        const firstSession =
          serverSessions.length > 0
            ? await fetchSessionMessages(serverSessions[0].id)
            : createSession();

        if (cancelled) {
          return;
        }

        setSessions(sortSessions([firstSession, ...serverSessions.slice(1)]));
        setActiveSessionId(firstSession.id);
        setInitializationFailed(false);
        setWebSocketEnabled(true);
      } catch (error) {
        if (!cancelled) {
          setInitializationFailed(true);
          setErrorMessage(error instanceof Error ? error.message : "服务端不可用");
        }
      }
    }

    void initialize();

    return () => {
      cancelled = true;
    };
  }, []);

  const loadSessionMessagesIfNeeded = useCallback(
    async (sessionId: string, sourceSessions = sessionsRef.current) => {
      const targetSession = sourceSessions.find((session) => session.id === sessionId);
      if (!targetSession || !targetSession.key || targetSession.messages.length > 0) {
        return;
      }

      try {
        const loadedSession = await fetchSessionMessages(sessionId);
        setSessions((currentSessions) =>
          sortSessions(
            currentSessions.map((session) =>
              session.id === loadedSession.id
                ? mergeLoadedSession(session, loadedSession)
                : session
            )
          )
        );
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "获取历史消息失败");
      }
    },
    []
  );

  const removeLocalSession = useCallback((sessionId: string) => {
    const result = removeSessionAndSelectNext(
      sessionsRef.current,
      sessionId,
      activeSessionIdRef.current
    );
    setSessions(result.sessions);
    setActiveSessionId(result.activeSessionId);
    return result;
  }, []);

  const handleMissingSession = useCallback(
    (sessionId: string) => {
      const result = removeLocalSession(sessionId);
      setErrorMessage("会话不存在或已被删除");

      if (result.activeSessionId) {
        void loadSessionMessagesIfNeeded(result.activeSessionId, result.sessions);
      }
    },
    [loadSessionMessagesIfNeeded, removeLocalSession]
  );

  function createNewSession() {
    const session = createSession();
    setSessions((currentSessions) => sortSessions([session, ...currentSessions]));
    setActiveSessionId(session.id);
    setErrorMessage(null);
  }

  async function selectSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setErrorMessage(null);

    try {
      const selectedSession = sessionsRef.current.find((session) => session.id === sessionId);
      if (selectedSession && !selectedSession.key) {
        return;
      }

      const session = await fetchSessionMessages(sessionId);
      setSessions((currentSessions) =>
        sortSessions(
          currentSessions.map((currentSession) =>
            currentSession.id === session.id
              ? mergeLoadedSession(currentSession, session)
              : currentSession
          )
        )
      );
    } catch (error) {
      if (error instanceof HttpError && error.status === 404) {
        handleMissingSession(sessionId);
        return;
      }

      setErrorMessage(error instanceof Error ? error.message : "获取历史消息失败");
    }
  }

  async function sendMessage() {
    const content = inputValue.trim();
    const sendingSessionId = activeSessionId;
    const sendingSession = activeSession;
    const attachmentsToSend = readyAttachments;

    if (
      (!content && attachmentsToSend.length === 0) ||
      isUploadingAttachments ||
      !sendingSessionId ||
      !sendingSession ||
      connectionStatus !== "connected"
    ) {
      return;
    }

    if (!sendingSession.key) {
      try {
        const remoteSession = await createRemoteSession(sendingSessionId);
        setSessions((currentSessions) =>
          mergeSessionSummary(currentSessions, remoteSession)
        );
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "创建会话失败");
        return;
      }
    }

    const userMessage = createMessage(
      "user",
      content || DEFAULT_ATTACHMENT_PROMPT,
      undefined,
      attachmentsToSend
    );
    setSessions((currentSessions) =>
      sortSessions(appendMessageToSession(currentSessions, sendingSessionId, userMessage))
    );
    setErrorMessage(null);

    if (!send(sendingSessionId, content, attachmentsToSend, userMessage.id)) {
      setSessions((currentSessions) =>
        currentSessions.map((session) =>
          session.id === sendingSessionId
            ? {
                ...session,
                messages: session.messages.slice(0, -1)
              }
            : session
        )
      );
      setErrorMessage("消息发送失败，请检查 WebSocket 连接");
      return;
    }

    clearDraft(sendingSessionId);
  }

  function removeAttachment(fileId: string) {
    setDraftAttachments((currentAttachments) =>
      currentAttachments.filter((attachment) => attachment.fileId !== fileId)
    );
  }

  function addFiles(files: File[]) {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }

    const validationError = validateFilesForAttachmentDraft(files, draftAttachments);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    const uploadingAttachments = files.map(createUploadingAttachment);
    setDraftAttachments((currentAttachments) => [...currentAttachments, ...uploadingAttachments]);
    setErrorMessage(null);

    uploadingAttachments.forEach((uploadingAttachment, index) => {
      void uploadAttachment(sessionId, files[index])
        .then((attachment) => {
          setDraftAttachments((currentAttachments) =>
            currentAttachments.map((currentAttachment) =>
              currentAttachment.fileId === uploadingAttachment.fileId
                ? toReadyDraftAttachment(attachment)
                : currentAttachment
            )
          );
        })
        .catch((error) => {
          setDraftAttachments((currentAttachments) =>
            currentAttachments.filter(
              (currentAttachment) => currentAttachment.fileId !== uploadingAttachment.fileId
            )
          );
          setErrorMessage(error instanceof Error ? error.message : "上传附件失败");
        });
    });
  }

  async function updatePinnedState(sessionId: string, pinned: boolean) {
    try {
      const updatedSession = pinned
        ? await pinSession(sessionId)
        : await unpinSession(sessionId);
      setSessions((currentSessions) => mergeSessionSummary(currentSessions, updatedSession));
      setErrorMessage(null);
    } catch (error) {
      if (error instanceof HttpError && error.status === 404) {
        handleMissingSession(sessionId);
        return;
      }

      setErrorMessage(
        error instanceof Error ? error.message : pinned ? "置顶会话失败" : "取消置顶会话失败"
      );
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await deleteRemoteSession(sessionId);
      clearDraft(sessionId);
      const result = removeLocalSession(sessionId);
      setErrorMessage(null);

      if (result.activeSessionId) {
        await loadSessionMessagesIfNeeded(result.activeSessionId, result.sessions);
      }
    } catch (error) {
      if (error instanceof HttpError && error.status === 404) {
        handleMissingSession(sessionId);
        return;
      }

      setErrorMessage(error instanceof Error ? error.message : "删除会话失败");
    }
  }

  return {
    sessions,
    activeSession,
    activeSessionId,
    connectionStatus: initializationFailed ? "disconnected" : connectionStatus,
    errorMessage,
    inputValue,
    inputDisabled:
      !activeSession || initializationFailed || connectionStatus !== "connected",
    draftAttachments,
    isUploadingAttachments,
    actions: {
      createSession: createNewSession,
      selectSession,
      sendMessage,
      pinSession: (sessionId: string) => updatePinnedState(sessionId, true),
      unpinSession: (sessionId: string) => updatePinnedState(sessionId, false),
      deleteSession,
      setInputValue,
      addFiles,
      removeAttachment,
      dismissError: () => setErrorMessage(null)
    }
  };
}
