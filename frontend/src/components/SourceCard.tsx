/** Clickable citation card: document name + page + chunk reference, expandable snippet. */

import { useState } from "react";

import type { Citation } from "../types";

export function SourceCard({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false);
  const pageLabel = citation.page !== null ? `Page ${citation.page}` : "No page";
  const refLabel = citation.reference ? ` · ref ${citation.reference}` : "";

  return (
    <button
      type="button"
      className={`source-card${expanded ? " source-card--expanded" : ""}`}
      onClick={() => setExpanded((value) => !value)}
      title={`${citation.document_name} · ${pageLabel}${refLabel} — click to ${expanded ? "hide" : "show"} excerpt`}
      data-testid="source-card"
    >
      <span className="source-card__top">
        <span className="source-card__doc" aria-label="source document">
          {citation.document_name}
        </span>
        <span className="source-card__ref">
          {pageLabel}
          {refLabel}
        </span>
      </span>
      {expanded && citation.snippet ? (
        <span className="source-card__snippet">{citation.snippet}</span>
      ) : null}
    </button>
  );
}