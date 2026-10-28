import { Suspense, useEffect, useRef } from "react";
import type { Concept } from "../api/types";
import { designChunk } from "../chunks";
import { lazyComponent } from "../lib/lazy";
import { Drafting, SheetUnavailable } from "./DesignDrafting";
import { ErrorBoundary } from "./ErrorBoundary";

/** The sheet's contents load with their own chunk the first time a sheet opens; its drafting state shows meanwhile. */
const DesignContent = lazyComponent(designChunk, (chunk) => chunk.DesignContent);

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

/**
 * A modal dialog: Escape, the Close button or a click on the backdrop closes it, and focus returns to its poster. It
 * opens with focus on the concept's name, so a screen reader starts with the sheet rather than its Close button.
 */
export function DesignSheet({ target, onClose }: DesignSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (target && !element.open) {
      element.showModal();
      element.querySelector<HTMLElement>("#design-title")?.focus({ preventScroll: true });
    } else if (!target && element.open) element.close();
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
        <ErrorBoundary
          key={`${target.runId}:${target.index}`}
          fallback={
            <div className="design-body">
              <SheetUnavailable concept={target.concept} />
            </div>
          }
        >
          <Suspense
            fallback={
              <div className="design-body" aria-busy="true">
                <Drafting concept={target.concept} index={target.index} />
              </div>
            }
          >
            <DesignContent runId={target.runId} index={target.index} concept={target.concept} />
          </Suspense>
        </ErrorBoundary>
      ) : null}
    </dialog>
  );
}
