import { useState } from "react";

/** Open by default where the map has room for it beside the sheet; a tap away on phones and tablets. */
const ROOMY = "(min-width: 981px)";

interface LegendProps {
  walkMinutes: number;
  gapGenre: string | null;
}

export function Legend({ walkMinutes, gapGenre }: LegendProps) {
  const [open] = useState(() => window.matchMedia(ROOMY).matches);
  return (
    <details className="legend" open={open}>
      <summary className="mono">Legend</summary>
      <div className="legend-body mono">
        <span>
          <i className="lg-site" />
          Site
        </span>
        <span>
          <i className="lg-ring" />
          <b>{walkMinutes}-min walk</b>
        </span>
        <span>
          <i className="lg-place" />
          Places nearby
        </span>
        <span>
          <i className="lg-comp" />
          Competitors
        </span>
        <span>
          <i className="lg-fav" />
          Loved here more than citywide
        </span>
        <span>
          <i className="lg-famous" />
          City&apos;s famous spots
        </span>
        <span>
          <i className="lg-grid" />
          <b>{gapGenre ? `Taste grid · ${gapGenre}` : "Taste grid"}</b>
        </span>
      </div>
    </details>
  );
}
