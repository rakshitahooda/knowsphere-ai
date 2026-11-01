/** Tests: typed API client (api/client.ts) — validation, DELETES, SSE streaming. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deleteDocument,
  describeError,
  fetchConversationMessages,
  fetchConversations,
  fetchDocuments,
  fetchHealth,
  streamChat,
  uploadDocument,
  validateFile,
} from "../api/client";
import type { ChatEvent } from "../types";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sseStream(blocks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const block of blocks) {
        controller.enqueue(encoder.encode(block));
      }
      controller.close();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

class MockXHR {
  static instances: MockXHR[] = [];
  response: unknown = null;
  responseType = "text";
  status = 0;
  upload = { onprogress: null as ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  sent = false;
  method = "";
  url = "";

  constructor() {
    MockXHR.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send() {
    this.sent = true;
  }
}

beforeEach(() => {
  MockXHR.instances = [];
  vi.stubGlobal(
    "XMLHttpRequest",
    MockXHR as unknown as typeof XMLHttpRequest,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// health & documents
// ---------------------------------------------------------------------------

describe("fetchHealth", () => {
  it("returns the parsed health payload", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(200, { status: "ok", app_name: "KnowSphere AI", version: "0.1.0", llm_provider: "ollama", embedding_model: "x" }),
    ));

    const health = await fetchHealth();

    expect(health.app_name).toBe("KnowSphere AI");
    expect(health.llm_provider).toBe("ollama");
  });
});

describe("fetchDocuments", () => {
  it("maps the backend list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(200, [
        { id: "d1", original_name: "a.pdf", stored_name: "s", content_type: "application/pdf", size_bytes: 10, num_chunks: 3, status: "ready", created_at: "2026-01-01T00:00:00Z" },
      ]),
    ));

    const docs = await fetchDocuments();

    expect(docs).toHaveLength(1);
    expect(docs[0]?.num_chunks).toBe(3);
  });

  it("throws ApiError with backend detail on 4xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(409, { detail: "Duplicate file" }),
    ));

    const error = await fetchDocuments().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).detail).toBe("Duplicate file");
  });
});

describe("uploadDocument", () => {
  it("POSTs multipart form and reports progress", async () => {
    const progress: number[] = [];
    const promise = uploadDocument(new File(["hello"], "a.txt"), (p) => progress.push(p));

    const xhr = await vi.waitFor(() => {
      const instance = MockXHR.instances[0];
      if (!instance || !instance.sent) throw new Error("xhr not sent yet");
      return instance;
    });

    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/documents");

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 5 });
    xhr.response = { id: "d1", original_name: "a.txt", size_bytes: 5, num_chunks: 1, status: "ready" };
    xhr.status = 201;
    xhr.onload?.();

    const created = await promise;
    expect(created.original_name).toBe("a.txt");
    expect(progress).toEqual([80]);
  });

  it("rejects with ApiError including backend detail on failure", async () => {
    const promise = uploadDocument(new File(["x"], "a.txt"));
    const xhr = await vi.waitFor(() => MockXHR.instances[0]!);

    xhr.response = { detail: "Unsupported file type" };
    xhr.status = 415;
    xhr.onload?.();

    const error = await promise.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(415);
    expect((error as ApiError).detail).toBe("Unsupported file type");
  });
});

describe("deleteDocument", () => {
  it("DELETEs the document", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteDocument("d1");

    expect(fetchMock).toHaveBeenCalledWith("/api/documents/d1", { method: "DELETE" });
  });
});

// ---------------------------------------------------------------------------
// conversations
// ---------------------------------------------------------------------------

describe("conversations", () => {
  it("fetches the conversation list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(200, [{ id: "c1", title: "hello", created_at: "x", message_count: 2 }]),
    ));

    const list = await fetchConversations();
    expect(list[0]?.message_count).toBe(2);
  });

  it("fetches conversation messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(200, [{ role: "user", content: "hi", citations: null, created_at: "y" }]),
    ));

    const messages = await fetchConversationMessages("c1");
    expect(messages[0]?.content).toBe("hi");
  });
});

// ---------------------------------------------------------------------------
// streamChat
// ---------------------------------------------------------------------------

describe("streamChat", () => {
  it("emits all parsed SSE events in order", async () => {
    const blocks = [
      'event: meta\ndata: {"conversation_id":"c1","has_context":true,"top_k":5,"citations":[]}\n\n',
      'event: delta\ndata: {"text":"li"}\n\n',
      'event: delta\ndata: {"text":"vor"}\n\n',
      'event: done\ndata: {"conversation_id":"c1"}\n\n',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseStream(blocks)));

    const events: ChatEvent[] = [];
    await streamChat({ question: "q", onEvent: (event) => events.push(event) });

    expect(events.map((e) => e.name)).toEqual(["meta", "delta", "delta", "done"]);
    const [first, second] = events as [ChatEvent, ChatEvent];
    expect(first).toMatchObject({ name: "meta" });
    expect(second).toEqual({ name: "delta", text: "li" });
  });

  it("rejects on pre-stream HTTP validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(400, { detail: "question must not be empty" })));

    await expect(
      streamChat({ question: "x", onEvent: () => undefined }),
    ).rejects.toMatchObject({ status: 400, detail: "question must not be empty" });
  });

  it("sends JSON body with conversation_id null by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseStream([]));
    vi.stubGlobal("fetch", fetchMock);

    await streamChat({ question: "q", onEvent: () => undefined });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ question: "q", conversation_id: null });
  });
});

// ---------------------------------------------------------------------------
// validation & error mapping
// ---------------------------------------------------------------------------

describe("validateFile", () => {
  it("rejects unsupported extensions", () => {
    const error = validateFile(new File(["x"], "evil.exe"), new Set());
    expect(error).toMatch(/Unsupported/);
  });

  it("accepts each allowed extension", () => {
    for (const name of ["a.pdf", "b.txt", "c.md", "d.docx"]) {
      expect(validateFile(new File(["x"], name), new Set())).toBeNull();
    }
  });

  it("rejects oversized files (>20 MB)", () => {
    const big = new File(["x"], "big.pdf");
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    expect(validateFile(big, new Set())).toMatch(/too large/);
  });

  it("rejects duplicates by name", () => {
    expect(validateFile(new File(["x"], "a.pdf"), new Set(["a.pdf"]))).toMatch(/already/);
  });
});

describe("describeError", () => {
  it("maps known statuses to friendly copy", () => {
    expect(describeError(new ApiError(413, ""))).toMatch(/too large/i);
    expect(describeError(new ApiError(409, ""))).toMatch(/already/i);
  });

  it("maps network TypeErrors", () => {
    expect(describeError(new TypeError("Failed to fetch"))).toMatch(/unreachable/i);
  });
});