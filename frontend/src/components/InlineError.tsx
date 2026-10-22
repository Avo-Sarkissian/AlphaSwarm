// One inline error row. The text comes from formatApiError or a
// backend RunError message, never from a raw exception object.
export interface InlineErrorProps {
  error: string | null;
  onDismiss?: () => void;
}

export function InlineError({ error, onDismiss }: InlineErrorProps) {
  if (!error) return null;
  return (
    <div className="inline-error" role="alert">
      <span className="inline-error-text">{error}</span>
      {onDismiss && (
        <button
          type="button"
          className="btn ghost inline-error-dismiss"
          aria-label="Dismiss error"
          onClick={onDismiss}
        >
          ×
        </button>
      )}
    </div>
  );
}
