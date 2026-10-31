import type { ReactNode } from "react";

type ErrorAction = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
};

export function errorMessage(reason: unknown, fallback = "Something went wrong. Try again."): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}

export function ActionableError({
  title = "Unable to continue",
  message,
  primaryAction,
  secondaryAction,
  compact = false,
}: {
  title?: string;
  message: ReactNode;
  primaryAction?: ErrorAction;
  secondaryAction?: ErrorAction;
  compact?: boolean;
}) {
  return (
    <section
      className={`actionable-error${compact ? " actionable-error--compact" : ""}`}
      role="alert"
      aria-live="assertive"
    >
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      {(primaryAction || secondaryAction) && (
        <div className="actionable-error__actions">
          {primaryAction && (
            <button
              className="primary"
              type="button"
              onClick={primaryAction.onClick}
              disabled={primaryAction.disabled}
            >
              {primaryAction.label}
            </button>
          )}
          {secondaryAction && (
            <button
              className="secondary"
              type="button"
              onClick={secondaryAction.onClick}
              disabled={secondaryAction.disabled}
            >
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
