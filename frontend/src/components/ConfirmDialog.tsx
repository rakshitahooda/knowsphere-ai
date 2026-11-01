/** Reusable confirmation dialog (dark glass, current design system). */

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
  testId,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
  testId: string;
}) {
  return (
    <div
      className="confirm-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid={testId}
      onClick={onCancel}
    >
      <div className="confirm-box" role="document" onClick={(event) => event.stopPropagation()}>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="confirm-box__actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--danger"
            autoFocus
            disabled={busy === true}
            onClick={onConfirm}
          >
            {busy ? "Deleting…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}