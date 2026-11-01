/** Composer: textarea + send/stop. Enter sends, Shift+Enter newlines. */

import { useState } from "react";

export function ChatInput({
  disabled,
  isStreaming,
  onSend,
  onStop,
}: {
  disabled: boolean;
  isStreaming: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isStreaming) {
      return;
    }
    onSend(trimmed);
    setValue("");
  };

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        className="chat-input__field"
        placeholder="Ask a question about your documents…"
        value={value}
        disabled={disabled || isStreaming}
        rows={2}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      {isStreaming ? (
        <button
          type="button"
          className="chat-input__button chat-input__button--stop"
          onClick={onStop}
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          className="chat-input__button"
          disabled={disabled || value.trim().length === 0}
        >
          Send
        </button>
      )}
    </form>
  );
}