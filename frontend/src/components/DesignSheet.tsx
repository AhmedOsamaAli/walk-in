import { useEffect, useRef } from "react";
import type { Concept } from "../api/types";
import { DesignContent } from "./DesignContent";

export interface DesignTarget {
  runId: string;
  index: number;
  concept: Concept;
  /** Where focus returns when the sheet closes. */
  opener: HTMLElement | null;
}

interface DesignSheetProps {
  target: DesignTarget | null;
  onClose: () => void;
}

/** A modal dialog: Escape, the Close button or a click on the backdrop closes it, and focus returns to its poster. */
export function DesignSheet({ target, onClose }: DesignSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (target && !element.open) element.showModal();
    else if (!target && element.open) element.close();
  }, [target]);

  return (
    <dialog
      ref={dialog}
      className="design"
      aria-labelledby="design-title"
      onClose={() => {
        const opener = target?.opener;
        onClose();
        opener?.focus();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.close();
      }}
    >
      <button
        className="design-close mono"
        type="button"
        onClick={() => {
          dialog.current?.close();
        }}
      >
        Close
      </button>
      {target ? (
        <DesignContent key={`${target.runId}:${target.index}`} runId={target.runId} index={target.index} concept={target.concept} />
      ) : null}
    </dialog>
  );
}
