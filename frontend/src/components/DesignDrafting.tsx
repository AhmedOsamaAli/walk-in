import type { ReactNode } from "react";
import type { Concept } from "../api/types";
import { letter } from "../lib/format";

/**
 * Focus starts on the sheet's title when it opens (DesignSheet.tsx). The drafting title gives way to the finished
 * sheet's, so the new title takes focus over when the old one had it, and leaves it wherever the reader has moved it.
 */
function keepFocus(title: HTMLHeadingElement | null): void {
  const dialog = title?.closest("dialog");
  if (!title || !dialog?.open) return;
  const active = document.activeElement;
  if (active === null || active === document.body || active === dialog) title.focus({ preventScroll: true });
}

/** The sheet's title, which labels the dialog and is where focus lands; a heading, so it draws no focus ring. */
export function SheetTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="d-title" id="design-title" tabIndex={-1} ref={keepFocus}>
      {children}
    </h2>
  );
}

/** A design sheet while it is drawn: its concept's name over the shapes of what is coming. */
export function Drafting({ concept, index }: { concept: Concept; index: number }) {
  return (
    <div className="d-main">
      <p className="d-eyebrow mono">Design sheet · Concept {letter(index)} · drafting</p>
      <SheetTitle>{concept.name}</SheetTitle>
      <div className="sk sk-line" />
      <div className="sk sk-line" />
      <div className="sk sk-block" />
      <div className="sk sk-block short" />
    </div>
  );
}

/** A design sheet whose code would not load: its concept's name, and what to do. */
export function SheetUnavailable({ concept }: { concept: Concept }) {
  return (
    <div className="d-main">
      <p className="d-eyebrow mono">Design sheet</p>
      <SheetTitle>{concept.name}</SheetTitle>
      <p className="d-p" role="alert">
        This design sheet could not be shown. Reload the page to try again.
      </p>
    </div>
  );
}
