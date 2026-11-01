/** M6 tests: conversation rename + delete flows via the full ChatWindow. */

import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";

import { useEffect } from "react";

import * as client from "../api/client";
import { ChatWindow } from "../components/ChatWindow";
import { useChats } from "../hooks/useChats";
import type { Conversation } from "../types";

const CONVERSATIONS: Conversation[] = [
  { id: "c1", title: "dogs", created_at: "t", message_count: 2 },
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

function itemFor(title: string): HTMLElement {
  const items = screen.getAllByTestId("conversation-item");
  const found = items.find((item) => item.textContent?.includes(title));
  if (!found) {
    throw new Error(`no conversation item containing ${title}`);
  }
  return found;
}

afterEach(() => {
  vi.restoreAllMocks();
});

// --------------------------------------------------------------------- //
// rename                                                                 //
// --------------------------------------------------------------------- //

describe("rename", () => {
  it("enters inline edit, saves on Enter and updates the list instantly", async () => {
    stubConversations();
    const renameSpy = vi.spyOn(client, "renameConversation").mockResolvedValue({
      id: "c1",
      title: "loyal companions",
      created_at: "t",
      message_count: 2,
    });

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Rename dogs/));
    const input = await screen.findByLabelText("Conversation title");
    await act(async () => {
      fireEvent.change(input, { target: { value: "loyal companions" } });
      fireEvent.keyDown(input, { key: "Enter" });
    });

    expect(renameSpy).toHaveBeenCalledWith("c1", "loyal companions");
    await waitFor(() => expect(screen.getByText("loyal companions")).toBeTruthy());
  });

  it("cancels on Escape without calling the API", async () => {
    stubConversations();
    const renameSpy = vi.spyOn(client, "renameConversation");

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Rename dogs/));
    const input = await screen.findByLabelText("Conversation title");
    fireEvent.input(input, { target: { value: "nope" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(renameSpy).not.toHaveBeenCalled();
    expect(screen.getByText("dogs")).toBeTruthy();
  });

  it("shows a sidebar error and rolls back on API failure", async () => {
    stubConversations();
    vi.spyOn(client, "renameConversation").mockRejectedValue(new client.ApiError(500, "500 boom"));

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Rename dogs/));
    const input = await screen.findByLabelText("Conversation title");
    await act(async () => {
      fireEvent.change(input, { target: { value: "riskier" } });
      fireEvent.keyDown(input, { key: "Enter" });
    });

    await waitFor(() => expect(screen.getByTestId("sidebar-error")).toBeTruthy());
    expect(screen.getByText("500 boom")).toBeTruthy();
    expect(screen.getByText("dogs")).toBeTruthy(); // optimistic title rolled back
  });

  it("blur commits the edit as well", async () => {
    stubConversations();
    const renameSpy = vi
      .spyOn(client, "renameConversation")
      .mockResolvedValue({ id: "c1", title: "blurred name", created_at: "t", message_count: 2 });

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Rename dogs/));
    const input = await screen.findByLabelText("Conversation title");
    fireEvent.input(input, { target: { value: "blurred name" } });
    fireEvent.blur(input);

    expect(renameSpy).toHaveBeenCalledWith("c1", "blurred name");
  });
});

// --------------------------------------------------------------------- //
// delete                                                                 //
// --------------------------------------------------------------------- //

describe("delete", () => {
  it("requires confirmation and removes the row on confirm", async () => {
    stubConversations();
    const deleteSpy = vi.spyOn(client, "deleteConversation").mockResolvedValue(undefined);

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Delete dogs/));
    const dialog = screen.getByTestId("conversation-delete-confirm");
    expect(dialog.textContent).toContain("cannot be undone");
    expect(deleteSpy).not.toHaveBeenCalled(); // not yet confirmed

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith("c1"));
    await waitFor(() => {
      const items = screen.queryAllByTestId("conversation-item");
      expect(items.length).toBe(1);
      expect(items[0]?.textContent).toContain("physics");
    });
  });

  it("closes the confirmation dialog on cancel", async () => {
    stubConversations();
    const deleteSpy = vi.spyOn(client, "deleteConversation");

    render(<Harness />);
    await waitFor(() => expect(itemFor("physics")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Delete physics/));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByTestId("conversation-delete-confirm")).toBeNull();
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it("shows an error banner when the delete API fails", async () => {
    stubConversations();
    vi.spyOn(client, "deleteConversation").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<Harness />);
    await waitFor(() => expect(itemFor("dogs")).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Delete dogs/));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByTestId("sidebar-error")).toBeTruthy());
    expect(screen.getByText(/unreachable/i)).toBeTruthy();
    expect(itemFor("dogs")).toBeTruthy(); // row stays (delete rolled back by omission)
  });
});