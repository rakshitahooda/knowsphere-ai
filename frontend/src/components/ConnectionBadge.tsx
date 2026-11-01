/** Connection indicator with live provider info tooltip. */

import type { BackendHealth } from "../hooks/useBackendHealth";

const LABEL: Record<BackendHealth["status"], string> = {
  checking: "Checking…",
  online: "Connected",
  offline: "Offline",
};

export function ConnectionBadge({ health }: { health: BackendHealth }) {
  const dotClass = {
    checking: "status-dot status-dot--checking",
    online: "status-dot status-dot--online",
    offline: "status-dot status-dot--offline",
  }[health.status];

  return (
    <div
      className={`connection-badge connection-badge--${health.status}`}
      title={
        health.status === "online" && health.info
          ? `${health.info.app_name} v${health.info.version} · LLM: ${health.info.llm_provider} · Embedder: ${health.info.embedding_model}`
          : (health.error ?? "Waiting for backend…")
      }
    >
      <span className={dotClass} aria-hidden="true" />
      <span className="connection-badge__label">{LABEL[health.status]}</span>
    </div>
  );
}