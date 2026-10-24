import type { MouseEvent, ReactNode } from "react";
import { safeLink } from "../lib/format";

const stop = (event: MouseEvent) => {
  event.stopPropagation();
};

/** A place's name, linked to its own menu or website when Qloo has one; links never trigger the card they sit in. */
export function PlaceLink({ name, url, kind, children }: { name: string; url?: string | null; kind?: string | null; children?: ReactNode }) {
  const href = safeLink(url);
  if (!href) return <>{children ?? name}</>;
  const what = kind === "menu" ? "menu" : "website";
  return (
    <a
      className="place-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`${name}: open its ${what}`}
      onClick={stop}
    >
      {children ?? name}
      <span aria-hidden="true">↗</span>
      <span className="sr-only"> (opens its {what})</span>
    </a>
  );
}
