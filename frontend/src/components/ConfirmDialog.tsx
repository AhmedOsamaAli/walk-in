import { useEffect, useId, useRef, type ReactNode } from "react";
import { cx } from "../lib/css";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  /** The confirming button's words: "Close the campaign". */
  confirm: string;
  /** The button that changes nothing: "Keep it open". */
  cancel: string;
  /** The action cannot be undone, so its button is drawn as a warning. */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** A modal question before an action that cannot be undone; Escape, the backdrop or the safe button keep things as they are. */
export function ConfirmDialog({ open, title, children, confirm, cancel, danger = false, onConfirm, onCancel }: ConfirmDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const safe = useRef<HTMLButtonElement>(null);
  const confirmed = useRef(false);
  const titleId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      confirmed.current = false;
      element.showModal();
      safe.current?.focus();
    } else if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="confirm"
      aria-labelledby={titleId}
      onClose={() => {
        if (confirmed.current) onConfirm();
        else onCancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.close();
      }}
    >
      <div className="confirm-inner">
        <h2 className="confirm-title" id={titleId}>
          {title}
        </h2>
        <div className="confirm-body">{children}</div>
        <div className="confirm-actions">
          <button
            ref={safe}
            type="button"
            className="ghost mono"
            onClick={() => {
              dialog.current?.close();
            }}
          >
            {cancel}
          </button>
          <button
            type="button"
            className={cx("ink-button", danger && "danger")}
            onClick={() => {
              confirmed.current = true;
              dialog.current?.close();
            }}
          >
            {confirm}
          </button>
        </div>
      </div>
    </dialog>
  );
}
