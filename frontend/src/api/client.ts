/**
 * Typed backend client — ALL network I/O for the frontend lives here.
 *
 * M3: document endpoints (upload with progress, list, delete).
 * M1/M2: health check.
 *
 * Components never call fetch directly; hooks consume this module, so the
 * transport stays swappable and testable.
 */

import type { ChatEvent, Conversation, DocumentMeta, MessageRecord } from "../types";
import { parseSseBlock, parseSseChunks } from "./sse";

export type ProviderName = "ollama" | "openrouter";

export interface Health {
  status: string;
  app_name: string;
  version: string;
  llm_provider: ProviderName;
  embedding_model: string;
}

export const ACCEPTED_UPLOAD_TYPES = [
  "application/pdf",
  "text/plain",
  "text/markdown",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
] as const;

export const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".md", ".docx"] as const;
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // mirrors backend MAX_UPLOAD_BYTES
export const MAX_PARAGRAPH_LEN = 2000;

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function assertOk(res: Response): Promise<Response> {
  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
  return res;
}

/** Classify any thrown error into a short, user-facing message. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return "File too large (max 20 MB).";
    if (error.status === 415) return "Unsupported file type.";
    if (error.status === 409) return "This document is already uploaded.";
    return error.detail;
  }
  if (error instanceof TypeError) {
    return "Backend unreachable — is the server running?";
  }
  if (error instanceof Error && error.message.startsWith("Request failed")) {
    return error.message;
  }
  return "Unexpected error.";
}

/** Validate a File against the upload contract; returns an error reason or null. */
export function validateFile(file: File, existingNames: Set<string>): string | null {
  const lower = file.name.toLowerCase();
  const hasValidExt = ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
  if (!hasValidExt) {
    return "Unsupported file type (allowed: PDF, TXT, MD, DOCX).";
  }
  if (file.size === 0) {
    return "File is empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "File too large (max 20 MB).";
  }
  // Deduplication display-guess: the backend 409s on stored-name collision,
  // but we can already catch the obvious same-name re-upload.
  if (existingNames.has(file.name)) {
    return "A document with this name is already uploaded.";
  }
  return null;
}

// ---------------------------------------------------------------------------
// health
// ---------------------------------------------------------------------------

export async function fetchHealth(): Promise<Health> {
  const res = await assertOk(await fetch("/api/health"));
  return (await res.json()) as Health;
}

// ---------------------------------------------------------------------------
// documents
// ---------------------------------------------------------------------------

export async function fetchDocuments(): Promise<DocumentMeta[]> {
  const res = await assertOk(await fetch("/api/documents"));
  const body = (await res.json()) as Array<Record<string, unknown>>;
  return body.map(coerceDocument);
}

function coerceDocument(raw: Record<string, unknown>): DocumentMeta {
  return {
    id: String(raw.id ?? ""),
    original_name: String(raw.original_name ?? "unknown"),
    stored_name: String(raw.stored_name ?? ""),
    content_type: String(raw.content_type ?? ""),
    size_bytes: typeof raw.size_bytes === "number" ? raw.size_bytes : 0,
    num_chunks: typeof raw.num_chunks === "number" ? raw.num_chunks : 0,
    status: String(raw.status ?? "unknown"),
    created_at: String(raw.created_at ?? ""),
  };
}

/**
 * Upload a file with upload-progress reporting (XHR — fetch cannot report
 * upload progress). Resolves with the created DocumentMeta.
 */
export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<DocumentMeta> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    xhr.responseType = "json";

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(coerceDocument((xhr.response ?? {}) as Record<string, unknown>));
      } else {
        let detail = `Upload failed with status ${xhr.status}`;
        const body = xhr.response as { detail?: unknown } | null;
        if (body && typeof body.detail === "string") detail = body.detail;
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new TypeError("network error"));
    xhr.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));
    if (signal) {
      signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(form);
  });
}

export async function deleteDocument(id: string): Promise<void> {
  await assertOk(await fetch(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

// ---------------------------------------------------------------------------
// conversations
// ---------------------------------------------------------------------------

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await assertOk(await fetch("/api/conversations"));
  return (await res.json()) as Conversation[];
}

export async function fetchConversationMessages(
  conversationId: string,
): Promise<MessageRecord[]> {
  const res = await assertOk(
    await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages`),
  );
  return (await res.json()) as MessageRecord[];
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<Conversation> {
  const res = await assertOk(
    await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
  return (await res.json()) as Conversation;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await assertOk(
    await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    }),
  );
}

// ---------------------------------------------------------------------------
// chat (SSE streaming)
// ---------------------------------------------------------------------------

export interface ChatRequestOptions {
  question: string;
  conversationId?: string | null;
  signal?: AbortSignal;
  /** Called per fully-parsed SSE event, in stream order. */
  onEvent: (event: ChatEvent) => void;
}

/**
 * POST /api/chat and consume the SSE stream incrementally.
 *
 * `onEvent` fires for every complete parsed event; malformed blocks are
 * skipped (parser tolerates them), non-200 status rejects before streaming.
 */
export async function streamChat(options: ChatRequestOptions): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: options.question,
      conversation_id: options.conversationId ?? null,
    }),
    signal: options.signal,
  });
  await assertOk(res); // validation errors arrive here before any streaming
  const body = res.body;
  if (!body) throw new TypeError("Streaming not supported in this browser");

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseChunks(buffer);
      buffer = parsed.remainder;
      for (const event of parsed.events) {
        options.onEvent(event);
      }
    }
    if (done) {
      // flush any trailing block (defense: our server always ends blocks
      // with \n\n, but tolerate servers that omit the final separator)
      const tail = parseSseBlock(buffer);
      if (tail) {
        options.onEvent(tail);
      }
      return;
    }
  }
}
