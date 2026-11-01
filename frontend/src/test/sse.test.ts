/** Tests: incremental SSE parsing (api/sse.ts). */

import { describe, expect, it } from "vitest";

import { parseSseBlock, parseSseChunks } from "../api/sse";

const META_BLOCK =
  'event: meta\ndata: {"conversation_id":"abc","has_context":true,"top_k":5,"citations":[{"position":1,"document_id":"d1","document_name":"pets.pdf","page":3,"section":1,"chunk_index":4,"reference":"p3·s1","snippet":"dog text"}]}';

describe("parseSseBlock", () => {
  it("parses a meta event into camelCase shape", () => {
    const event = parseSseBlock(META_BLOCK);

    expect(event).toEqual({
      name: "meta",
      meta: {
        conversationId: "abc",
        hasContext: true,
        topK: 5,
        citations: [
          {
            position: 1,
            document_id: "d1",
            document_name: "pets.pdf",
            page: 3,
            section: 1,
            chunk_index: 4,
            reference: "p3·s1",
            snippet: "dog text",
          },
        ],
      },
    });
  });

  it("parses delta events", () => {
    expect(parseSseBlock('event: delta\ndata: {"text":"hello "}')).toEqual({
      name: "delta",
      text: "hello ",
    });
  });

  it("parses error events with kind and message", () => {
    expect(
      parseSseBlock('event: error\ndata: {"kind":"provider_unavailable","message":"down"}'),
    ).toEqual({ name: "error", kind: "provider_unavailable", message: "down" });
  });

  it("parses done events", () => {
    expect(parseSseBlock('event: done\ndata: {"conversation_id":"abc"}')).toEqual({
      name: "done",
      conversationId: "abc",
    });
  });

  it("tolerates comment lines and blank lines inside a block", () => {
    const event = parseSseBlock(': keep-alive comment\nevent: delta\ndata: {"text":"x"}\n');
    expect(event).toEqual({ name: "delta", text: "x" });
  });

  it("tolerates CRLF line endings", () => {
    const event = parseSseBlock('event: delta\r\ndata: {"text":"x"}\r');
    expect(event).toEqual({ name: "delta", text: "x" });
  });

  it("returns null for malformed JSON", () => {
    expect(parseSseBlock("event: delta\ndata: {not json")).toBeNull();
  });

  it("returns null for unknown event types", () => {
    expect(parseSseBlock('event: telemetry\ndata: {"x":1}')).toBeNull();
  });

  it("returns null for blocks missing data", () => {
    expect(parseSseBlock("event: delta\nid: 12")).toBeNull();
  });

  it("coerces citations with missing optional fields defensively", () => {
    const event = parseSseBlock(
      'event: meta\ndata: {"conversation_id":"c","has_context":false,"top_k":"?","citations":[{"document_id":"d","document_name":"n"}]}',
    );

    expect(event).toEqual({
      name: "meta",
      meta: {
        conversationId: "c",
        hasContext: false,
        topK: 0,
        citations: [
          {
            position: 0,
            document_id: "d",
            document_name: "n",
            page: null,
            section: 0,
            chunk_index: 0,
            reference: "",
            snippet: "",
          },
        ],
      },
    });
  });
});

describe("parseSseChunks (incremental)", () => {
  const TWO_EVENTS = `${META_BLOCK}\n\nevent: delta\ndata: {"text":"hello "}\n\n`;

  it("extracts complete events and keeps the incomplete remainder", () => {
    const partial = TWO_EVENTS.slice(0, Math.floor(TWO_EVENTS.length / 2)); // mid-block
    const parsed = parseSseChunks(partial);

    // the first event may or may not be complete at the cut; remainder grows
    expect(parsed.remainder.length).toBeGreaterThan(0);
    expect(parsed.events.length).toBeLessThanOrEqual(1);
  });

  it("emits both events once the buffer is complete and empties the remainder", () => {
    const parsed = parseSseChunks(TWO_EVENTS);
    expect(parsed.events.map((e) => e.name)).toEqual(["meta", "delta"]);
    expect(parsed.remainder).toBe("");
  });

  it("supports feeding in arbitrary fragments (stream simulation)", () => {
    const fragments = ["event: ", 'delta\ndata: {"', 'text":"a"}', "\n\nevent", ": don", 'e\ndata: {"conversation_id":"c"}', "\n\n"];
    let buffer = "";
    const events = [];
    for (const fragment of fragments) {
      buffer += fragment;
      const parsed = parseSseChunks(buffer);
      buffer = parsed.remainder;
      events.push(...parsed.events);
    }

    expect(events.map((e) => e.name)).toEqual(["delta", "done"]);
  });

  it("ignores trailing garbage without a data line", () => {
    const parsed = parseSseChunks(META_BLOCK + "\n\nevent: delta\n(no data)");
    expect(parsed.events.length).toBe(1);
    expect(parsed.events[0]?.name).toBe("meta");
  });
});