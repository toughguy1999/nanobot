"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DraftAttachment } from "../model/chat.types";
import { toReadyDraftAttachment } from "../model/attachments";
import { validateAttachments } from "../services/chatApi";

export const CHAT_DRAFTS_STORAGE_KEY = "nanobot:web:chat-drafts:v1";

type StoredDraft = {
  inputValue: string;
  attachments: DraftAttachment[];
};

type StoredDrafts = Record<string, StoredDraft>;

const EMPTY_DRAFT: StoredDraft = {
  inputValue: "",
  attachments: []
};

function readStoredDrafts(): StoredDrafts {
  try {
    const rawValue = window.localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY);
    if (!rawValue) {
      return {};
    }

    const parsed = JSON.parse(rawValue) as unknown;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }

    return Object.entries(parsed as Record<string, StoredDraft>).reduce<StoredDrafts>(
      (drafts, [sessionId, draft]) => {
        if (!draft || typeof draft.inputValue !== "string" || !Array.isArray(draft.attachments)) {
          return drafts;
        }

        drafts[sessionId] = {
          inputValue: draft.inputValue,
          attachments: draft.attachments.filter(
            (attachment) =>
              attachment &&
              typeof attachment.fileId === "string" &&
              attachment.status === "ready"
          )
        };
        return drafts;
      },
      {}
    );
  } catch {
    return {};
  }
}

function writeStoredDrafts(drafts: StoredDrafts) {
  try {
    if (Object.keys(drafts).length === 0) {
      window.localStorage.removeItem(CHAT_DRAFTS_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, JSON.stringify(drafts));
  } catch {
    // Local draft persistence is best effort.
  }
}

export function useAttachmentDrafts(activeSessionId: string | null) {
  const draftsRef = useRef<StoredDrafts>({});
  const initializedRef = useRef(false);
  const [inputValue, setInputValueState] = useState("");
  const [draftAttachments, setDraftAttachmentsState] = useState<DraftAttachment[]>([]);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const inputValueRef = useRef(inputValue);
  const draftAttachmentsRef = useRef(draftAttachments);
  const activeSessionIdRef = useRef(activeSessionId);

  inputValueRef.current = inputValue;
  draftAttachmentsRef.current = draftAttachments;
  activeSessionIdRef.current = activeSessionId;

  useEffect(() => {
    if (!initializedRef.current) {
      draftsRef.current = readStoredDrafts();
      initializedRef.current = true;
    }
  }, []);

  const updateDraft = useCallback((sessionId: string, draft: StoredDraft) => {
    const readyAttachments = draft.attachments.filter(
      (attachment) => attachment.status === "ready"
    );
    const nextDrafts = {
      ...draftsRef.current,
      [sessionId]: {
        inputValue: draft.inputValue,
        attachments: readyAttachments
      }
    };

    if (!draft.inputValue && readyAttachments.length === 0) {
      delete nextDrafts[sessionId];
    }

    draftsRef.current = nextDrafts;
    writeStoredDrafts(nextDrafts);
  }, []);

  const setInputValue = useCallback(
    (value: string) => {
      inputValueRef.current = value;
      setInputValueState(value);
      if (!activeSessionId) {
        return;
      }
      updateDraft(activeSessionId, {
        inputValue: value,
        attachments: draftAttachmentsRef.current
      });
    },
    [activeSessionId, updateDraft]
  );

  const setDraftAttachments = useCallback(
    (nextAttachments: DraftAttachment[] | ((current: DraftAttachment[]) => DraftAttachment[])) => {
      setDraftAttachmentsState((currentAttachments) => {
        const attachments =
          typeof nextAttachments === "function"
            ? nextAttachments(currentAttachments)
            : nextAttachments;
        const sessionId = activeSessionIdRef.current;
        if (sessionId) {
          updateDraft(sessionId, {
            inputValue: inputValueRef.current,
            attachments
          });
        }
        return attachments;
      });
    },
    [updateDraft]
  );

  useEffect(() => {
    if (!activeSessionId) {
      setInputValueState("");
      setDraftAttachmentsState([]);
      return;
    }

    const draft = draftsRef.current[activeSessionId] ?? EMPTY_DRAFT;
    setInputValueState(draft.inputValue);
    setDraftAttachmentsState(draft.attachments);
    setRecoveryError(null);

    const readyIds = draft.attachments
      .filter((attachment) => attachment.status === "ready")
      .map((attachment) => attachment.fileId);
    if (readyIds.length === 0) {
      return;
    }

    let cancelled = false;
    void validateAttachments(activeSessionId, readyIds)
      .then(({ valid, invalid }) => {
        if (cancelled || invalid.length === 0) {
          return;
        }

        const validIds = new Set(valid.map((attachment) => attachment.fileId));
        const restoredAttachments = valid.map(toReadyDraftAttachment);
        setDraftAttachmentsState(restoredAttachments);
        updateDraft(activeSessionId, {
          inputValue: draft.inputValue,
          attachments: restoredAttachments
        });
        if (draft.attachments.some((attachment) => !validIds.has(attachment.fileId))) {
          setRecoveryError("部分附件已失效，请重新上传");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRecoveryError("附件草稿校验失败，请重新上传");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, updateDraft]);

  const clearDraft = useCallback(
    (sessionId: string) => {
      const nextDrafts = { ...draftsRef.current };
      delete nextDrafts[sessionId];
      draftsRef.current = nextDrafts;
      writeStoredDrafts(nextDrafts);

      if (activeSessionId === sessionId) {
        setInputValueState("");
        setDraftAttachmentsState([]);
      }
    },
    [activeSessionId]
  );

  return {
    inputValue,
    draftAttachments,
    recoveryError,
    setInputValue,
    setDraftAttachments,
    clearDraft
  };
}
