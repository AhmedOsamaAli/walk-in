import { useEffect, useState } from "react";
import { siteName } from "../lib/fullmap";
import type { Site } from "../state/site";

export interface NextStepProps {
  /** The site chosen on the brief, or null. */
  site: Site | null;
  /** The brief is the screen shown, and the full-screen map is not over it. */
  active: boolean;
  /** "Use this spot": the brief's next step comes into view and focus, as from the full-screen map. */
  onUse: () => void;
}

/**
 * Phones and tablets, where the map sits above the sheet: once a site is placed, "Use this spot" waits at the foot of
 * the screen while the brief it opens is out of sight below, so the next step is one tap away and nothing scrolls while
 * the pin may still be moving. Wide screens show the brief beside the map, and never this (layout.css).
 */
export function NextStep({ site, active, onUse }: NextStepProps) {
  const spot = site ? `${site.lat},${site.lon}` : null;
  /** Whether the brief's card is below the screen, for the spot it was measured for. */
  const [below, setBelow] = useState<{ spot: string; below: boolean } | null>(null);

  useEffect(() => {
    if (!active || spot === null) return;
    const card = document.querySelector("#s-brief .brief-card");
    if (!card) return;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries.at(-1);
      if (!entry) return;
      const bottom = entry.rootBounds?.bottom ?? window.innerHeight;
      setBelow({ spot, below: !entry.isIntersecting && entry.boundingClientRect.top >= bottom - 1 });
    });
    observer.observe(card);
    return () => {
      observer.disconnect();
    };
  }, [active, spot]);

  if (!active || !site || below?.spot !== spot || !below.below) return null;
  return (
    <button type="button" className="next-pill" onClick={onUse}>
      <span className="next-pill-text">
        <b>Use this spot</b>
        <span className="next-pill-site">{siteName(site)}</span>
      </span>
      <i aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M12 4v15M6 13l6 6 6-6" />
        </svg>
      </i>
    </button>
  );
}
