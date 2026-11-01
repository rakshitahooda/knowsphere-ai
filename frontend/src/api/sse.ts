/** Incremental SSE parser for the /api/chat event stream.
 *
 * Pure string-to-event mapping (no fetch, no React) so it is fully unit
 * testable. Works on chunks of any granularity: `parseSseChunks` splits a
 * growing buffer at SSE block boundaries ("\n\n") and returns both the
 * *complete* events and the unconsumed remainder.
 */

import type { ChatDeltaEvent, ChatDoneEvent, ChatErrorEvent, ChatEvent, ChatMetaEvent, Citation, ChatStreamMeta } from "../types";

export interface ParsedBuffer {
  events: ChatEvent[];
  remainder: string;
}

export function parseSseChunks(buffer: string): ParsedBuffer {
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() ?? "";
  const events: ChatEvent[] = [];
  for (const block of parts) {
    const event = parseSseBlock(block);
    if (event !== null) {
      events.push(event);
    }
  }
  return { events, remainder };
}

/** Parse ONE complete SSE block ("event: x\ndata: {...}"). */
export function parseSseBlock(block: string): ChatEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "" || line.startsWith(":")) {
      continue; // separators and ": keep-alive" comments
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
    // unknown fields are ignored (SSE spec)
  }
  if (dataLines.length === 0) {
    return null;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return null; // tolerate malformed blocks instead of killing the stream
  }
  if (typeof payload !== "object" || payload === null) {
    return null;
  }
  return toChatEvent(eventName, payload as Record<string, unknown>);
}

function toChatEvent(name: string, payload: Record<string, unknown>): ChatEvent | null {
  switch (name) {
    case "meta": {
      if (typeof payload.conversation_id !== "string") {
        return null;
      }
      const meta: ChatStreamMeta = {
        conversationId: payload.conversation_id,
        hasContext: payload.has_context === true,
        topK: typeof payload.top_k === "number" ? payload.top_k : 0,
        citations: Array.isArray(payload.citations)
          ? payload.citations.map(coerceCitation).filter((c): c is Citation => c !== null)
          : [],
      };
      const event: ChatMetaEvent = { name: "meta", meta };
      return event;
    }
    case "delta": {
      if (typeof payload.text !== "string") {
        return null;
      }
      const event: ChatDeltaEvent = { name: "delta", text: payload.text };
      return event;
    }
    case "error": {
      const event: ChatErrorEvent = {
        name: "error",
        kind: typeof payload.kind === "string" ? payload.kind : "unknown",
        message: typeof payload.message === "string" ? payload.message : "Unknown error",
      };
      return event;
    }
    case "done": {
      if (typeof payload.conversation_id !== "string") {
        return null;
      }
      const event: ChatDoneEvent = { name: "done", conversationId: payload.conversation_id };
      return event;
    }
    default:
      return null;
  }
}

function coerceCitation(raw: unknown): Citation | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const value = raw as Record<string, unknown>;
  if (typeof value.document_id !== "string" || typeof value.document_name !== "string") {
    return null;
  }
  return {
    position: typeof value.position === "number" ? value.position : 0,
    document_id: value.document_id,
    document_name: value.document_name,
    page: typeof value.page === "number" ? value.page : null,
    section: typeof value.section === "number" ? value.section : 0,
    chunk_index: typeof value.chunk_index === "number" ? value.chunk_index : 0,
    reference: typeof value.reference === "string" ? value.reference : "",
    snippet: typeof value.snippet === "string" ? value.snippet : "",
  };
}
