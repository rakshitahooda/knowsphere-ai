/** Tests: ChatWindow streaming behavior + useChats state machine. */

import { useEffect } from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatWindow } from "../components/ChatWindow";
import { ChatInput } from "../components/ChatInput";
import { useChats } from "../hooks/useChats";
import * as client from "../api/client";
import type { ChatEvent, Conversation } from "../types";

const CONVERSATIONS: Conversation[] = [
  { id: "c1", title: "dogs and balls", created_at: "t", message_count: 2 },
  { id: "c2", title: "physics", created_at: "t2", message_count: 4 },
];

function Harness() {
  const chats = useChats();

  useEffect(() => {
    void chats.refreshConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <ChatWindow
      conversations={chats.conversations}
      activeConversationId={chats.activeConversationId}
      messages={chats.messages}
      isStreaming={chats.isStreaming}
      loadingMessages={chats.loadingMessages}
      isBackendOnline={true}
      deletingIds={chats.deletingIds}
      busyIds={chats.busyIds}
      managementError={chats.managementError}
      onOpenConversation={(id) => void chats.openConversation(id)}
      onNewConversation={chats.newConversation}
      onSend={(question) => void chats.send(question)}
      onStop={chats.stopStreaming}
      onRename={(id, title) => void chats.rename(id, title)}
      onDeleteConfirm={(id) => void chats.deleteById(id)}
      onDismissError={chats.clearManagementError}
    />
  );
}

function stubConversations() {
  return vi.spyOn(client, "fetchConversations").mockResolvedValue(CONVERSATIONS);
}

describe("ChatWindow", () => {
  it("shows the empty hero when no messages exist", () => {
    render(<ChatWindow
      conversations={[]}
      activeConversationId={null}
      messages={[]}
      isStreaming={false}
      loadingMessages={false}
      isBackendOnline={true}
      deletingIds={new Set()}
      busyIds={new Set()}
      managementError={null}
      onOpenConversation={() => undefined}
      onNewConversation={() => undefined}
      onSend={() => undefined}
      onStop={() => undefined}
      onRename={() => undefined}
      onDeleteConfirm={() => undefined}
      onDismissError={() => undefined}
    />);

    expect(screen.getByText(/Ask your documents anything/)).toBeTruthy();
  });

  it("lists conversations and marks the active one", () => {
    render(<ChatWindow
      conversations={CONVERSATIONS}
      activeConversationId="c2"
      messages={[]}
      isStreaming={false}
      loadingMessages={false}
      isBackendOnline={true}
      deletingIds={new Set()}
      busyIds={new Set()}
      managementError={null}
      onOpenConversation={() => undefined}
      onNewConversation={() => undefined}
      onSend={() => undefined}
      onStop={() => undefined}
      onRename={() => undefined}
      onDeleteConfirm={() => undefined}
      onDismissError={() => undefined}
    />);

    const list = screen.getByTestId("conversation-list");
    expect(list.textContent).toContain("physics");
    const items = list.querySelectorAll("[data-testid='conversation-item']");
    expect(items.length).toBe(2);
    expect(items[1]?.className).toContain("conversation-item--active");
  });
});

describe("ChatInput", () => {
  it("Enter sends, Shift+Enter does not, whitespace is not sent", () => {
    const onSend = vi.fn();
    render(<ChatInput disabled={false} isStreaming={false} onSend={onSend} onStop={() => undefined} />);
    const field = screen.getByPlaceholderText(/Ask a question/) as HTMLTextAreaElement;

    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: "real question" } });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("real question");
    expect(field.value).toBe(""); // cleared after send
  });

  it("disables send while streaming and offers Stop instead", () => {
    const onStop = vi.fn();
    render(<ChatInput disabled={false} isStreaming={true} onSend={() => undefined} onStop={onStop} />);

    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });

  it("disables input when the backend is offline", () => {
    render(<ChatInput disabled={true} isStreaming={false} onSend={() => undefined} onStop={() => undefined} />);
    expect((screen.getByPlaceholderText(/Ask a question/) as HTMLTextAreaElement).disabled).toBe(true);
  });
});

describe("useChats end-to-end streaming (mocked client)", () => {
  it("streams meta → deltas → done into the visible thread", async () => {
    const conversationSpy = stubConversations();
    const events: ChatEvent[] = [
      {
        name: "meta",
        meta: {
          conversationId: "new-1",
          hasContext: true,
          topK: 5,
          citations: [{
            position: 1, document_id: "d1", document_name: "pets.pdf", page: 2,
            section: 1, chunk_index: 0, reference: "p2·s1", snippet: "dog text",
          }],
        },
      },
      { name: "delta", text: "Dogs " },
      { name: "delta", text: "chase balls." },
      { name: "done", conversationId: "new-1" },
    ];
    vi.spyOn(client, "streamChat").mockImplementation(async (options) => {
      for (const event of events) {
        options.onEvent(event);
      }
    });
    void conversationSpy;

    render(<Harness />);

    await act(async () => {
      fireEvent.change(screen.getByPlaceholderText(/Ask a question/), {
        target: { value: "what about dogs?" },
      });
    });
    fireEvent.keyDown(screen.getByPlaceholderText(/Ask a question/), { key: "Enter" });

    await waitFor(() => expect(screen.getByText("Dogs chase balls.")).toBeTruthy());
    expect(screen.getByText("pets.pdf")).toBeTruthy(); // citations live
    // after the stream completes, the composer is usable again
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeTruthy());
  });

  it("renders in-stream errors without losing the partial answer", async () => {
    stubConversations();
    vi.spyOn(client, "streamChat").mockImplementation(async (options) => {
      options.onEvent({ name: "delta", text: "partial" });
      options.onEvent({ name: "error", kind: "provider_unavailable", message: "ollama down" });
    });

    render(<Harness />);
    await act(async () => {
      fireEvent.change(screen.getByPlaceholderText(/Ask a question/), {
        target: { value: "q" },
      });
    });
    fireEvent.keyDown(screen.getByPlaceholderText(/Ask a question/), { key: "Enter" });

    await waitFor(() => expect(screen.getByTestId("assistant-bubble").textContent).toContain("partial"));
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/provider is unreachable/i)).toBeTruthy();
  });

  it("shows a network error when the fetch itself rejects", async () => {
    stubConversations();
    vi.spyOn(client, "streamChat").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<Harness />);
    await act(async () => {
      fireEvent.change(screen.getByPlaceholderText(/Ask a question/), {
        target: { value: "q" },
      });
    });
    fireEvent.keyDown(screen.getByPlaceholderText(/Ask a question/), { key: "Enter" });

    await waitFor(() => expect(screen.getByText(/Connection problem/)).toBeTruthy());
  });

  it("loads a conversation's history on click", async () => {
    stubConversations();
    vi.spyOn(client, "fetchConversationMessages").mockResolvedValue([
      { role: "user", content: "old question", citations: null, created_at: "t" },
      {
        role: "assistant",
        content: "old answer",
        citations: [{
          position: 1, document_id: "d", document_name: "old.pdf", page: 1,
          section: 0, chunk_index: 0, reference: "p1·s0", snippet: "s",
        }],
        created_at: "t2",
      },
    ]);

    render(<Harness />);
    await waitFor(() => expect(screen.getByText("physics")).toBeTruthy());
    fireEvent.click(screen.getByText("physics"));

    await waitFor(() => expect(screen.getByText("old answer")).toBeTruthy());
    expect(screen.getByText("old question")).toBeTruthy();
    expect(screen.getByText("old.pdf")).toBeTruthy(); // historic citations render too
  });
});