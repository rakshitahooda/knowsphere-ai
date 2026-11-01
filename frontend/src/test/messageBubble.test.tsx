/** Tests: MessageBubble + SourceCard — streaming render and citations. */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble } from "../components/MessageBubble";
import type { ChatMessageVM } from "../hooks/useChats";
import type { Citation } from "../types";

const CITATION: Citation = {
  position: 1,
  document_id: "doc-1",
  document_name: "pets.pdf",
  page: 3,
  section: 1,
  chunk_index: 4,
  reference: "p3·s1",
  snippet: "Dog chases ball in the yard.",
};

function makeAssistant(partial: Partial<ChatMessageVM>): ChatMessageVM {
  return {
    id: "a1",
    role: "assistant",
    content: "",
    citations: null,
    status: "final",
    errorKind: null,
    errorMessage: null,
    ...partial,
  };
}

describe("MessageBubble (user)", () => {
  it("renders the user text without sources", () => {
    render(<MessageBubble message={{ id: "u1", role: "user", content: "What about dogs?", citations: null, status: "final", errorKind: null, errorMessage: null }} />);

    expect(screen.getByText("What about dogs?")).toBeTruthy();
    expect(screen.queryByTestId("citation-list")).toBeNull();
  });
});

describe("MessageBubble (assistant)", () => {
  it("shows typing dots while streaming with no content yet", () => {
    render(<MessageBubble message={makeAssistant({ status: "streaming" })} />);

    expect(screen.getByLabelText(/typing/i)).toBeTruthy();
  });

  it("renders streamed content progressively", () => {
    const { rerender } = render(
      <MessageBubble message={makeAssistant({ status: "streaming", content: "hello" })} />,
    );
    expect(screen.getByText("hello")).toBeTruthy();

    rerender(<MessageBubble message={makeAssistant({ status: "streaming", content: "hello world" })} />);
    expect(screen.getByText("hello world")).toBeTruthy();
  });

  it("renders citations after the meta event as clickable source cards", () => {
    render(
      <MessageBubble
        message={makeAssistant({
          status: "final",
          content: "Dogs chase balls.",
          citations: [CITATION],
        })}
      />,
    );

    expect(screen.getByTestId("citation-list")).toBeTruthy();
    expect(screen.getByText("pets.pdf")).toBeTruthy();
    expect(screen.getByText(/Page 3/)).toBeTruthy();
    expect(screen.getByText(/1 source/)).toBeTruthy();
  });

  it("expands a source card on click to reveal the snippet", () => {
    render(
      <MessageBubble
        message={makeAssistant({ status: "final", content: "x", citations: [CITATION] })}
      />,
    );

    expect(screen.queryByText("Dog chases ball in the yard.")).toBeNull();
    fireEvent.click(screen.getByTestId("source-card"));
    expect(screen.getByText("Dog chases ball in the yard.")).toBeTruthy();
  });

  it("does not render a sources block when there are no citations", () => {
    render(<MessageBubble message={makeAssistant({ status: "final", content: "answer" })} />);
    expect(screen.queryByTestId("citation-list")).toBeNull();
  });

  it("renders friendly error copy with backend detail", () => {
    render(
      <MessageBubble
        message={makeAssistant({
          status: "error",
          errorKind: "provider_unavailable",
          errorMessage: "Ollama connect failed",
        })}
      />,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/provider is unreachable/i)).toBeTruthy();
    expect(screen.getByText("Ollama connect failed")).toBeTruthy();
  });

  it("renders the neutral no-context answer without any sources", () => {
    render(
      <MessageBubble
        message={makeAssistant({
          status: "final",
          content: "I could not find anything relevant…",
          citations: [],
        })}
      />,
    );

    expect(screen.getByText(/could not find anything/i)).toBeTruthy();
    expect(screen.queryByTestId("citation-list")).toBeNull();
  });
});