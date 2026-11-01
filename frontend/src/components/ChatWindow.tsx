/** Right side: conversation list (rename/delete), message thread, composer. */

import { useState, type ReactNode } from "react";

import type { ChatMessageVM } from "../hooks/useChats";
import type { Conversation } from "../types";
import { ChatInput } from "./ChatInput";
import { ConfirmDialog } from "./ConfirmDialog";
import { MessageBubble } from "./MessageBubble";

export function ChatWindow({
  conversations,
  activeConversationId,
  messages,
  isStreaming,
  loadingMessages,
  isBackendOnline,
  deletingIds,
  busyIds,
  managementError,
  onOpenConversation,
  onNewConversation,
  onSend,
  onStop,
  onRename,
  onDeleteConfirm,
  onDismissError,
}: {
  conversations: Conversation[] | null;
  activeConversationId: string | null;
  messages: ChatMessageVM[];
  isStreaming: boolean;
  loadingMessages: boolean;
  isBackendOnline: boolean;
  deletingIds: ReadonlySet<string>;
  busyIds: ReadonlySet<string>;
  managementError: string | null;
  onOpenConversation: (id: string) => void;
  onNewConversation: () => void;
  onSend: (question: string) => void;
  onStop: () => void;
  onRename: (id: string, title: string) => void;
  onDeleteConfirm: (id: string) => void;
  onDismissError: () => void;
}) {
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);

  return (
    <section className="chat-window">
      <div className="chat-window__sidebar">
        <button type="button" className="btn btn--primary btn--full" onClick={onNewConversation}>
          New conversation
        </button>

        {managementError ? (
          <div className="sidebar-error" role="alert" data-testid="sidebar-error">
            <span>{managementError}</span>
            <button type="button" aria-label="Dismiss error" onClick={onDismissError}>
              ×
            </button>
          </div>
        ) : null}

        <nav className="conversation-list" aria-label="Conversations" data-testid="conversation-list">
          {conversations === null ? (
            <p className="conversation-list__empty">Loading…</p>
          ) : conversations.length === 0 ? (
            <p className="conversation-list__empty" data-testid="conversation-list-empty">
              No conversations yet.
            </p>
          ) : (
            conversations.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                active={conversation.id === activeConversationId}
                busy={busyIds.has(conversation.id)}
                deleting={deletingIds.has(conversation.id)}
                onOpen={onOpenConversation}
                onRename={onRename}
                onDelete={(conv) => {
                  setPendingDelete(conv);
                }}
              />
            ))
          )}
        </nav>
      </div>

      <div className="chat-thread" data-testid="chat-thread">
        <MessagesArea messages={messages} loadingMessages={loadingMessages} />
        <ChatInput
          disabled={!isBackendOnline}
          isStreaming={isStreaming}
          onSend={onSend}
          onStop={onStop}
        />
      </div>

      {pendingDelete ? (
        <ConfirmDialog
          title="Delete conversation?"
          body={`"${pendingDelete.title}" and its full message history will be removed. This cannot be undone.`}
          confirmLabel="Delete"
          busy={deletingIds.has(pendingDelete.id)}
          testId="conversation-delete-confirm"
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            onDeleteConfirm(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      ) : null}
    </section>
  );
}

/**
 * One conversation row: click → open; pencil → inline rename (Enter saves,
 * Esc cancels); trash → delete flow (confirmation handled by ChatWindow).
 */
export function ConversationItem({
  conversation,
  active,
  busy,
  deleting,
  onOpen,
  onRename,
  onDelete,
}: {
  conversation: Conversation;
  active: boolean;
  busy: boolean;
  deleting: boolean;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (conversation: Conversation) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);

  const startEdit = () => {
    setDraft(conversation.title);
    setEditing(true);
  };

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed.length > 0) {
      onRename(conversation.id, trimmed);
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="conversation-item conversation-item--editing">
        <input
          aria-label="Conversation title"
          className="conversation-item__input"
          value={draft}
          disabled={busy}
          autoFocus
          maxLength={120}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") setEditing(false);
          }}
          onBlur={commit}
        />
      </div>
    );
  }

  return (
    <div
      className={`conversation-item${active ? " conversation-item--active" : ""}${
        deleting ? " conversation-item--deleting" : ""
      }`}
      data-testid="conversation-item"
    >
      <button
        type="button"
        className="conversation-item__open"
        title={conversation.title}
        disabled={deleting}
        onClick={() => onOpen(conversation.id)}
      >
        <span className="conversation-item__title">{conversation.title}</span>
        <span className="conversation-item__count">{conversation.message_count}</span>
      </button>
      <button
        type="button"
        className="conversation-item__action conversation-item__action--rename"
        aria-label={`Rename ${conversation.title}`}
        disabled={busy || deleting}
        onClick={startEdit}
      >
        ✎
      </button>
      <button
        type="button"
        className="conversation-item__action conversation-item__action--delete"
        aria-label={`Delete ${conversation.title}`}
        disabled={busy || deleting}
        onClick={() => onDelete(conversation)}
      >
        {deleting ? "…" : "🗑"}
      </button>
    </div>
  );
}

function MessagesArea({
  messages,
  loadingMessages,
}: {
  messages: ChatMessageVM[];
  loadingMessages: boolean;
}) {
  let body: ReactNode;
  if (loadingMessages) {
    body = <p className="chat-thread__placeholder">Loading conversation…</p>;
  } else if (messages.length === 0) {
    body = (
      <div className="chat-thread__hero">
        <h2>Ask your documents anything</h2>
        <p>
          Every answer is grounded in the sources you upload — citations show the
          exact document and page. If the documents don&apos;t contain the answer,
          the assistant says so instead of guessing.
        </p>
      </div>
    );
  } else {
    body = (
      <div className="message-list">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
      </div>
    );
  }
  return <div className="chat-thread__messages">{body}</div>;
}