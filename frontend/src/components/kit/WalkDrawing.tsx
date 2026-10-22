import { fitWalk } from "../../lib/kit";
import type { LatLon } from "../../api/types";

interface WalkDrawingProps {
  ring: LatLon[];
  site: LatLon;
  minutes: number;
  className?: string;
}

/** The walk's real outline around the site, drawn in the page's own ink: the dossier's cover plate. */
export function WalkDrawing({ ring, site, minutes, className }: WalkDrawingProps) {
  const fitted = fitWalk(ring, site, 360, 270, 30);
  const [x, y] = fitted.site;
  return (
    <svg className={className ? `walk-drawing ${className}` : "walk-drawing"} viewBox="0 0 360 270" role="img" aria-label={`The ${minutes}-minute walk around the site`}>
      <rect className="wd-paper" width="360" height="270" rx="14" />
      {fitted.path ? <path className="wd-walk" d={fitted.path} /> : null}
      <circle className="wd-halo" cx={x} cy={y} r="14" />
      <circle className="wd-site" cx={x} cy={y} r="4.5" />
      <text className="wd-label" x="16" y="252">
        {`${minutes}-MINUTE WALK`}
      </text>
      <g className="wd-north" transform="translate(338 30)">
        <path d="M0 -11L4.5 4L0 1L-4.5 4Z" />
        <text y="16" textAnchor="middle">
          N
        </text>
      </g>
    </svg>
  );
}
