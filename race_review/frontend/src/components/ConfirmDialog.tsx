import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export function ConfirmDialog({
  title,
  children,
  confirmLabel = "Confirm",
  matchValue,
  matchLabel,
  onConfirm,
  onCancel,
  busy = false,
  danger = false,
}: {
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  matchValue?: string;
  matchLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
  danger?: boolean;
}) {
  const headingId = useId();
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [typed, setTyped] = useState("");
  const matched = matchValue == null || typed === matchValue;
  useEffect(() => {
    const handle = requestAnimationFrame(() => closeButton.current?.focus());
    return () => cancelAnimationFrame(handle);
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(dialog.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
    ) ?? [])].filter((element) => !element.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="drawer-backdrop confirm-backdrop" onClick={onCancel}>
      <aside
        ref={dialog}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="section-heading">
          <h2 id={headingId}>{title}</h2>
          <button ref={closeButton} className="icon-button" type="button" onClick={onCancel}>
            CLOSE
          </button>
        </div>
        <div className="muted">{children}</div>
        {matchValue != null && (
          <label className="field">
            {matchLabel ?? "Type the session id to confirm"}
            <input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              aria-label={matchLabel ?? "Type the session id to confirm"}
              autoComplete="off"
            />
          </label>
        )}
        <div className="confirm-dialog__actions">
          <button className="secondary" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className={danger ? "primary" : "secondary"}
            type="button"
            onClick={onConfirm}
            disabled={busy || !matched}
          >
            {confirmLabel}
          </button>
        </div>
      </aside>
    </div>
  );
}
