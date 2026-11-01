/** Chat state machine: conversations, history, streaming responses (SSE). */

import { useCallback, useRef, useState } from "react";

import {
  deleteConversation,
  describeError,
  fetchConversationMessages,
  fetchConversations,
  renameConversation,
  streamChat,
} from "../api/client";
import type {
  Citation,
  ChatStreamMeta,
  Conversation,
  MessageRecord,
} from "../types";

export interface ChatMessageVM {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null; // live streaming citations while status=streaming
  status: "final" | "streaming" | "error";
  errorKind: string | null;
  errorMessage: string | null;
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export function useChats() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageVM[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(new Set());
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [managementError, setManagementError] = useState<string | null>(null);

  const abortStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await fetchConversations());
    } catch {
      setConversations([]);
    }
  }, []);

  /**
   * Rename a conversation. Optimistically updates the list, rolls back on
   * error, and surfaces a dismissible sidebar error message.
   */
  const rename = useCallback(
    async (conversationId: string, title: string) => {
      const trimmed = title.trim();
      if (!trimmed) {
        return;
      }
      setBusyIds((prev) => new Set(prev).add(conversationId));
      setManagementError(null);
      const previous = conversations;
      setConversations((prev) =>
        prev
          ? prev.map((item) =>
              item.id === conversationId ? { ...item, title: trimmed } : item,
            )
          : prev,
      );
      try {
        await renameConversation(conversationId, trimmed);
      } catch (error: unknown) {
        setConversations(previous); // roll back the optimistic title
        setManagementError(describeError(error));
      } finally {
        setBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(conversationId);
          return next;
        });
      }
    },
    [conversations],
  );

  const clearManagementError = useCallback(() => setManagementError(null), []);

  /**
   * Delete a conversation with per-item pending state. A conversation that
   * is open on deletion clears the message thread (card-level "New
   * conversation" behavior).
   */
  const deleteById = useCallback(
    async (conversationId: string) => {
      setDeletingIds((prev) => new Set(prev).add(conversationId));
      setManagementError(null);
      try {
        await deleteConversation(conversationId);
        setConversations((prev) =>
          prev ? prev.filter((item) => item.id !== conversationId) : prev,
        );
        if (activeConversationId === conversationId) {
          setActiveConversationId(null);
          setMessages([]);
          abortStreaming();
        }
      } catch (error: unknown) {
        setManagementError(describeError(error));
      } finally {
        setDeletingIds((prev) => {
          const next = new Set(prev);
          next.delete(conversationId);
          return next;
        });
      }
    },
    [abortStreaming, activeConversationId],
  );

  const openConversation = useCallback(
    async (conversationId: string) => {
      setActiveConversationId(conversationId);
      setLoadingMessages(true);
      abortStreaming(); // switching threads cancels an in-flight stream
      try {
        const records: MessageRecord[] = await fetchConversationMessages(conversationId);
        setMessages(records.map(toVmFromRecord));
      } catch {
        setMessages([]);
      } finally {
        setLoadingMessages(false);
      }
    },
    [abortStreaming],
  );

  const newConversation = useCallback(() => {
    abortStreaming();
    setActiveConversationId(null);
    setMessages([]);
  }, [abortStreaming]);

  /**
   * Send a question and stream the assistant reply into the message list.
   * The assistant placeholder is added optimistically; its identity is kept
   * stable and every SSE event patches just that message.
   */
  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) {
        return;
      }
      abortStreaming();

      const userMsg: ChatMessageVM = {
        id: nextId("u"),
        role: "user",
        content: trimmed,
        citations: null,
        status: "final",
        errorKind: null,
        errorMessage: null,
      };
      const assistantMsg: ChatMessageVM = {
        id: nextId("a"),
        role: "assistant",
        content: "",
        citations: null,
        status: "streaming",
        errorKind: null,
        errorMessage: null,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const patchAssistant = (patch: (msg: ChatMessageVM) => ChatMessageVM) => {
        setMessages((prev) =>
          prev.map((msg) => (msg.id === assistantMsg.id ? patch(msg) : msg)),
        );
      };

      try {
        await streamChat({
          question: trimmed,
          conversationId: activeConversationId,
          signal: controller.signal,
          onEvent: (event) => {
            switch (event.name) {
              case "meta": {
                const meta: ChatStreamMeta = event.meta;
                if (!activeConversationId) {
                  setActiveConversationId(meta.conversationId);
                }
                patchAssistant((msg) => ({ ...msg, citations: meta.citations }));
                break;
              }
              case "delta":
                patchAssistant((msg) => ({ ...msg, content: msg.content + event.text }));
                break;
              case "error":
                patchAssistant((msg) => ({
                  ...msg,
                  status: "error",
                  errorKind: event.kind,
                  errorMessage: event.message,
                }));
                break;
              case "done":
                patchAssistant((msg) => ({ ...msg, status: "final" }));
                break;
            }
          },
        });
        // stream ended without an error/done? mark final anyway
        patchAssistant((msg) => (msg.status === "streaming" ? { ...msg, status: "final" } : msg));
      } catch (error: unknown) {
        // network-level failure or HTTP validation error (fetch rejects here)
        patchAssistant((msg) => ({
          ...msg,
          status: "error",
          errorKind: "network",
          errorMessage: describeError(error),
        }));
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
        void refreshConversations();
      }
    },
    [activeConversationId, abortStreaming, isStreaming, refreshConversations],
  );

  const hasMessages = messages.length > 0;
  const lastAssistantId =
    hasMessages && messages[messages.length - 1].role === "assistant"
      ? messages[messages.length - 1].id
      : null;

  const stopStreaming = useCallback(() => {
    abortStreaming();
    patchFinalizeOnAbort();
  }, [abortStreaming]);

  function patchFinalizeOnAbort() {
    setMessages((prev) =>
      prev.map((msg) => (msg.status === "streaming" ? { ...msg, status: "final" } : msg)),
    );
  }

  return {
    conversations,
    activeConversationId,
    messages,
    isStreaming,
    loadingMessages,
    lastAssistantId,
    deletingIds,
    busyIds,
    managementError,
    refreshConversations,
    openConversation,
    newConversation,
    send,
    stopStreaming,
    rename,
    deleteById,
    clearManagementError,
  };
}

function toVmFromRecord(record: MessageRecord): ChatMessageVM {
  return {
    id: nextId(record.role === "user" ? "u" : "a"),
    role: record.role,
    content: record.content,
    citations: record.citations,
    status: "final",
    errorKind: null,
    errorMessage: null,
  };
}