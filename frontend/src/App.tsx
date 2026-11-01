/**
 * KnowSphere AI — application shell.
 *
 * Composes the health/news/document hooks into the two-rail layout:
 * left = documents, right = conversations + chat. Components are display
 * only; state machines live in hooks, transport in api/client.
 */

import { useEffect } from "react";

import { ChatWindow } from "./components/ChatWindow";
import { DocumentPanel } from "./components/DocumentPanel";
import { useBackendHealth } from "./hooks/useBackendHealth";
import { useChats } from "./hooks/useChats";
import { useDocuments } from "./hooks/useDocuments";

export default function App() {
  const health = useBackendHealth();
  const docs = useDocuments();
  const chats = useChats();

  // initial + reconnect loads
  useEffect(() => {
    void docs.load();
    void chats.refreshConversations();
    // hooks instances are stable across renders; load once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // refresh document list when the backend comes back online
  useEffect(() => {
    if (health.status === "online") {
      void docs.load();
      void chats.refreshConversations();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health.status]);

  return (
    <main className="app">
      <DocumentPanel
        health={health}
        documents={docs.documents}
        uploads={docs.uploads}
        deletingIds={docs.deletingIds}
        onFiles={(files) => void docs.uploadMany(files)}
        onDismissJob={docs.removeUploadJob}
        onDelete={(id) => void docs.remove(id)}
        isBackendOnline={health.status === "online"}
      />
      <ChatWindow
        conversations={chats.conversations}
        activeConversationId={chats.activeConversationId}
        messages={chats.messages}
        isStreaming={chats.isStreaming}
        loadingMessages={chats.loadingMessages}
        isBackendOnline={health.status === "online"}
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
    </main>
  );
}