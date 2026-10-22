import type { MouseEvent, ReactNode } from "react";
import type { PriceAnchor, PriceStep } from "../api/types";
import { cx } from "../lib/css";
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

/** The places whose prices define this level here; their menus show what it costs. */
export function PriceAnchors({ anchors, lead = "Priced like" }: { anchors: PriceAnchor[] | undefined; lead?: string }) {
  if (!anchors?.length) return null;
  const linked = anchors.some((anchor) => anchor.url);
  return (
    <p className="anchors">
      <span className="mono">{lead}</span>{" "}
      {anchors.map((anchor, index) => (
        <span key={anchor.name}>
          {index ? ", " : null}
          <PlaceLink name={anchor.name} url={anchor.url} kind={anchor.link} />
          {anchor.within_walk ? <small> (inside the walk)</small> : null}
        </span>
      ))}
      {linked ? <span className="anchors-hint">. Their menus show what this level costs here.</span> : "."}
    </p>
  );
}

/** Qloo's four price levels: dots for the places locals love, squares for the places inside the walk. */
export function PriceLadder({ ladder, level }: { ladder: PriceStep[] | undefined; level: number | null | undefined }) {
  if (!ladder?.some((step) => step.loved || step.inside)) return null;
  const label = ladder
    .map((step) => `${"$".repeat(step.level)}: ${step.loved} loved, ${step.inside} inside the walk`)
    .join("; ");
  return (
    <div className="ladder" role="img" aria-label={`Price levels. ${label}.`}>
      {ladder.map((step) => (
        <div key={step.level} className={cx("rung", step.level === level && "chosen", step.loved >= 2 && !step.inside && "open")}>
          <span className="rung-level mono">{"$".repeat(step.level)}</span>
          <span className="rung-marks" aria-hidden="true">
            {Array.from({ length: Math.min(step.loved, 8) }, (_, k) => (
              <i key={`l${k}`} className="loved" />
            ))}
            {Array.from({ length: Math.min(step.inside, 8) }, (_, k) => (
              <i key={`i${k}`} className="inside" />
            ))}
          </span>
        </div>
      ))}
      <span className="ladder-key mono" aria-hidden="true">
        <i className="loved" /> locals love <i className="inside" /> inside the walk
      </span>
    </div>
  );
}
