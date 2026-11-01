/** One message row: user bubble, assistant answer with live citations. */

import type { ChatMessageVM } from "../hooks/useChats";
import { SourceCard } from "./SourceCard";

const ERROR_LABEL: Record<string, string> = {
  provider_unavailable: "The LLM provider is unreachable. Is Ollama running (or OpenRouter reachable)?",
  provider_not_configured: "The LLM provider is not configured on the server.",
  network: "Connection problem.",
};

export function MessageBubble({ message }: { message: ChatMessageVM }) {
  if (message.role === "user") {
    return (
      <div className="message-row message-row--user">
        <div className="bubble bubble--user">{message.content}</div>
      </div>
    );
  }

  const isError = message.status === "error";
  const streaming = message.status === "streaming";
  const showContent = message.content.length > 0;
  const friendlyError = message.errorKind
    ? (ERROR_LABEL[message.errorKind] ?? "Something went wrong.")
    : "";

  return (
    <div className="message-row message-row--assistant">
      <div
        className={`bubble bubble--assistant${isError ? " bubble--error" : ""}`}
        data-testid="assistant-bubble"
      >
        {showContent ? <p className="bubble__text">{message.content}</p> : null}
        {streaming && !showContent ? <span className="typing-dots" aria-label="Assistant is typing" /> : null}
        {isError ? (
          <div className="bubble__error" role="alert">
            <strong>{friendlyError}</strong>
            <span className="bubble__error-detail">{message.errorMessage}</span>
          </div>
        ) : null}
        {message.citations && message.citations.length > 0 ? (
          <div className="bubble__sources" data-testid="citation-list">
            <span className="bubble__sources-label">
              {message.citations.length} source{message.citations.length === 1 ? "" : "s"}
            </span>
            <div className="source-cards">
              {message.citations.map((citation) => (
                <SourceCard key={`${citation.document_id}-${citation.position}`} citation={citation} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}