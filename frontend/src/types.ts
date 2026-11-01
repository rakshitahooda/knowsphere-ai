/** Shared DTOs — mirror of the backend API schemas (single typed boundary). */

export type HealthStatus = "checking" | "online" | "offline";

export interface Health {
  status: string;
  app_name: string;
  version: string;
  llm_provider: string;
  embedding_model: string;
}

export interface DocumentMeta {
  id: string;
  original_name: string;
  stored_name: string;
  content_type: string;
  size_bytes: number;
  num_chunks: number;
  status: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface Citation {
  position: number;
  document_id: string;
  document_name: string;
  page: number | null;
  section: number;
  chunk_index: number;
  reference: string;
  snippet: string;
}

export interface MessageRecord {
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  created_at: string;
}

export interface ChatStreamMeta {
  conversationId: string;
  hasContext: boolean;
  topK: number;
  citations: Citation[];
}

export type ChatEvent =
  | ChatMetaEvent
  | ChatDeltaEvent
  | ChatErrorEvent
  | ChatDoneEvent;

export interface ChatMetaEvent {
  name: "meta";
  meta: ChatStreamMeta;
}

export interface ChatDeltaEvent {
  name: "delta";
  text: string;
}

export interface ChatErrorEvent {
  name: "error";
  kind: string;
  message: string;
}

export interface ChatDoneEvent {
  name: "done";
  conversationId: string;
}
