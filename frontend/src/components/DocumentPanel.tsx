/** Left rail: connection, uploader, document library with delete confirm. */

import { useState } from "react";

import type { BackendHealth } from "../hooks/useBackendHealth";
import type { UploadJob } from "../hooks/useDocuments";
import type { DocumentMeta } from "../types";
import { ConnectionBadge } from "./ConnectionBadge";
import { DocumentUploader, UploadJobsList } from "./DocumentUploader";

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${bytes} B`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function DocumentPanel({
  health,
  documents,
  uploads,
  deletingIds,
  onFiles,
  onDismissJob,
  onDelete,
  isBackendOnline,
}: {
  health: BackendHealth;
  documents: DocumentMeta[] | null;
  uploads: UploadJob[];
  deletingIds: ReadonlySet<string>;
  onFiles: (files: File[]) => void;
  onDismissJob: (jobId: string) => void;
  onDelete: (id: string) => void;
  isBackendOnline: boolean;
}) {
  const [pendingDelete, setPendingDelete] = useState<DocumentMeta | null>(null);

  return (
    <aside className="doc-panel">
      <header className="doc-panel__head">
        <h1 className="brand">
          KnowSphere <span className="brand__ai">AI</span>
        </h1>
        <ConnectionBadge health={health} />
      </header>

      <DocumentUploader onFiles={onFiles} />
      <UploadJobsList jobs={uploads} onDismiss={onDismissJob} />

      <section className="doc-library" aria-label="Document library">
        <h2 className="doc-library__title">
          Library
          <span className="doc-library__count">
            {documents ? ` ${documents.length}` : ""}
          </span>
        </h2>
        {documents === null ? (
          <p className="doc-library__empty">Loading…</p>
        ) : documents.length === 0 ? (
          <p className="doc-library__empty" data-testid="empty-library">
            No documents yet. Upload something to start asking questions.
          </p>
        ) : (
          <ul className="doc-list">
            {documents.map((doc) => (
              <li key={doc.id} className="doc-item" data-testid="doc-item">
                <div className="doc-item__main">
                  <span className="doc-item__name" title={doc.original_name}>
                    {doc.original_name}
                  </span>
                  <span className="doc-item__meta">
                    {formatBytes(doc.size_bytes)} · {doc.num_chunks} chunks ·{" "}
                    {formatDate(doc.created_at)}
                  </span>
                </div>
                <span className={`doc-item__status doc-item__status--${doc.status}`}>
                  {doc.status}
                </span>
                <button
                  type="button"
                  className="doc-item__delete"
                  aria-label={`Delete ${doc.original_name}`}
                  disabled={deletingIds.has(doc.id) || !isBackendOnline}
                  onClick={() => setPendingDelete(doc)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {pendingDelete ? (
        <div
          className="confirm-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm deletion"
          data-testid="delete-confirm"
          onClick={() => setPendingDelete(null)}
        >
          <div
            className="confirm-box"
            role="document"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>Delete document?</h3>
            <p>
              <strong>{pendingDelete.original_name}</strong> and all its indexed
              chunks will be removed. This cannot be undone.
            </p>
            <div className="confirm-box__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setPendingDelete(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--danger"
                autoFocus
                onClick={() => {
                  onDelete(pendingDelete.id);
                  setPendingDelete(null);
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
}