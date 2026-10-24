import { useEffect, useId, useMemo, useRef, useState, type RefObject, type SVGAttributes } from "react";
import type { CoverMap, PosterMap, StreetMap } from "../../api/sitemap";
import type { LatLon } from "../../api/types";
import {
  dataEdge,
  fitFrame,
  linePath,
  placePins,
  placeTag,
  placeTrips,
  ringPath,
  scaleBar,
  STREET_LAYERS,
  tripPoint,
  type Box,
  type Frame,
  type PinMark,
  type TripInput,
  type TripMark,
} from "../../lib/sitemap";
import "../../styles/sitemap.css";

type Role =
  | "land"
  | "beyond"
  | "edge"
  | "water"
  | "park"
  | "casing"
  | "street"
  | "walkFill"
  | "walkLine"
  | "cross"
  | "siteFill"
  | "siteRing"
  | "tag"
  | "tagText"
  | "pinMain"
  | "pinMainText"
  | "pinSide"
  | "pinSideText"
  | "leader"
  | "shaft"
  | "head"
  | "pill"
  | "pillText"
  | "spot"
  | "spotText"
  | "note"
  | "scale"
  | "scaleText";

type Paint = (role: Role) => SVGAttributes<SVGElement>;

/** The report's map takes its colors from sitemap.css, so it follows the theme on screen and prints in light ink. */
const classPaint: Paint = (role) => ({ className: `sm-${role}` });

// A printed poster keeps its own colors whatever the screen's theme, written on each shape so a saved SVG keeps them.
const MONO = '"Geist Mono Variable", "Geist Mono", ui-monospace, Menlo, Consolas, monospace';
const INK = "#1d1d1f";
const PRINT: Record<Role, SVGAttributes<SVGElement>> = {
  land: { fill: "#f3f1ea" },
  beyond: { fill: "#fbfaf6" },
  edge: { fill: "none", stroke: "#b9b6ab", strokeWidth: 0.8, strokeDasharray: "3 3" },
  water: { fill: "#c9dcf0" },
  park: { fill: "#dfe8d3" },
  casing: { fill: "none", stroke: "#d3cfc4" },
  street: { fill: "none", stroke: "#ffffff" },
  walkFill: { fill: "#0f68ea", fillOpacity: 0.09 },
  walkLine: { fill: "none", stroke: "#0f68ea", strokeWidth: 2.4 },
  cross: { stroke: "#0f68ea", strokeWidth: 1 },
  siteFill: { fill: "#0f68ea" },
  siteRing: { fill: "#ffffff" },
  tag: { fill: "#0f68ea" },
  tagText: { fill: "#ffffff", fontFamily: MONO, fontWeight: 500 },
  pinMain: { fill: INK, stroke: "#ffffff", strokeWidth: 1.2 },
  pinMainText: { fill: "#ffffff", fontFamily: MONO, fontWeight: 600 },
  pinSide: { fill: "#ffffff", stroke: INK, strokeWidth: 1.2 },
  pinSideText: { fill: INK, fontFamily: MONO, fontWeight: 600 },
  leader: { stroke: INK, strokeWidth: 0.8 },
  shaft: { stroke: INK, strokeWidth: 1.5 },
  head: { fill: INK },
  pill: { fill: "#ffcb00", stroke: INK, strokeWidth: 0.8 },
  pillText: { fill: INK, fontFamily: MONO, fontWeight: 600 },
  spot: { fill: "#ffcb00", stroke: INK, strokeWidth: 1.2 },
  spotText: { fill: INK, fontFamily: MONO, fontWeight: 600 },
  note: { fill: "#5f5f59", fontFamily: MONO },
  scale: { fill: INK, stroke: INK },
  scaleText: { fill: INK, fontFamily: MONO, fontWeight: 500 },
};
const printPaint: Paint = (role) => PRINT[role];

/** Casing and fill widths per street layer, in frame units. */
const STREET_WIDTH = {
  primary: [5.6, 3.8],
  secondary: [4.2, 2.6],
  residential: [2.6, 1.3],
  pedestrian: [1.9, 0.8],
} as const;

const PIN_R = 8;
const LABEL = 9.5;
const measure = (text: string, size = LABEL) => text.length * size * 0.62 + 2;

interface Drawn {
  frame: Frame;
  streets: Partial<Record<keyof typeof STREET_WIDTH, string>>;
  water: string;
  parks: string;
  walk: string;
  edge: ReturnType<typeof dataEdge>;
  pins: PinMark[];
  trips: TripMark[];
  /** The site's tag. */
  tag: Box;
}

/** Everything in the frame, laid out once per size. */
function lay(
  streets: StreetMap | null,
  ring: LatLon[],
  site: LatLon,
  width: number,
  height: number,
  pins: CoverMap["pins"],
  trips: TripInput[],
  keepClear: Box[] = [],
  siteLabel = "SITE",
): Drawn {
  const frame = fitFrame(ring, site, { width, height, pad: Math.max(30, Math.min(width, height) * 0.12), box: streets?.box });
  const paths: Drawn["streets"] = {};
  if (streets) for (const layer of STREET_LAYERS) paths[layer] = linePath(streets.streets[layer] ?? [], frame.at);
  const marks = placePins(pins, frame, PIN_R);
  // Flags keep clear of the scale and north arrow (bottom right), the credit (bottom left), the pins and the site.
  const [sx, sy] = frame.site;
  const reserved = [
    { x: width - 128, y: height - 50, width: 128, height: 50 },
    { x: 0, y: height - 20, width: measure(noteOf(streets), 7.5) + 14, height: 20 },
    { x: sx - 12, y: sy - 12, width: 24, height: 24 },
    ...marks.map((mark) => {
      const r = (mark.numbered ? PIN_R : 3) + 1.5;
      return { x: mark.x - r, y: mark.y - r, width: 2 * r, height: 2 * r };
    }),
    ...keepClear,
  ];
  return {
    frame,
    streets: paths,
    water: streets ? ringPath(streets.water, frame.at) : "",
    parks: streets ? ringPath(streets.parks, frame.at) : "",
    walk: ringPath([ring], frame.at),
    edge: streets ? dataEdge(frame, streets.box) : null,
    pins: marks,
    trips: placeTrips(trips, frame, { inset: 8, height: 16, measure: (label) => measure(label), reserved }),
    tag: placeTag(frame, { width: measure(siteLabel, 8) + 8, height: 14 }, marks, PIN_R),
  };
}

function Head({ at, angle, paint }: { at: [number, number]; angle: number; paint: Paint }) {
  const [ux, uy] = [Math.cos(angle), Math.sin(angle)];
  const [x, y] = at;
  const r = (value: number) => Math.round(value * 10) / 10;
  const points = [
    [x + ux * 6.5, y + uy * 6.5],
    [x + ux * 0.5 - uy * 3.6, y + uy * 0.5 + ux * 3.6],
    [x + ux * 0.5 + uy * 3.6, y + uy * 0.5 - ux * 3.6],
  ]
    .map((p) => p.map(r).join(","))
    .join(" ");
  return (
    <g>
      <line x1={r(x - ux * 6)} y1={r(y - uy * 6)} x2={r(x + ux * 1.5)} y2={r(y + uy * 1.5)} {...paint("shaft")} strokeLinecap="round" />
      <polygon points={points} {...paint("head")} />
    </g>
  );
}

function Pill({ x, y, anchor, text, paint }: { x: number; y: number; anchor: "start" | "middle" | "end"; text: string; paint: Paint }) {
  const width = measure(text) + 6;
  const left = anchor === "start" ? x - 3 : anchor === "end" ? x - width + 3 : x - width / 2;
  return (
    <g>
      <rect x={left} y={y - LABEL + 0.5} width={width} height={LABEL + 4.5} rx={3} {...paint("pill")} />
      <text x={left + width / 2} y={y} textAnchor="middle" fontSize={LABEL} {...paint("pillText")}>
        {text}
      </text>
    </g>
  );
}

function Trips({ marks, paint, named }: { marks: TripMark[]; paint: Paint; named: boolean }) {
  return (
    <g>
      {marks.map((mark) =>
        mark.kind === "flag" ? (
          <g key={`f-${mark.label}`}>
            <rect x={mark.x} y={mark.y} width={mark.width} height={mark.height} rx={mark.height / 2} {...paint("pill")} />
            <Head at={mark.head} angle={mark.angle} paint={paint} />
            <text x={mark.textAt[0]} y={mark.textAt[1]} fontSize={LABEL} {...paint("pillText")}>
              {mark.label}
            </text>
          </g>
        ) : named ? (
          <g key={`s-${mark.label}`}>
            <circle cx={mark.x} cy={mark.y} r={7.5} {...paint("spot")} />
            <text x={mark.x} y={mark.y + 3.4} textAnchor="middle" fontSize={9.5} {...paint("spotText")}>
              {mark.keys.join("")}
            </text>
          </g>
        ) : (
          <g key={`s-${mark.label}`}>
            <circle cx={mark.x} cy={mark.y} r={4.5} {...paint("spot")} />
            <Pill x={mark.x + 9} y={mark.y + 3.6} anchor="start" text={mark.label} paint={paint} />
          </g>
        ),
      )}
    </g>
  );
}

function Pins({ marks, paint }: { marks: PinMark[]; paint: Paint }) {
  const dots = marks.filter((mark) => !mark.numbered);
  const numbered = marks.flatMap((mark) => (mark.n === null ? [] : [{ ...mark, n: mark.n }])).sort((a, b) => b.n - a.n);
  return (
    <g>
      {dots.map((mark, index) => (
        <circle key={`d-${String(index)}`} cx={mark.x} cy={mark.y} r={2.8} {...paint(mark.main ? "pinMain" : "pinSide")} strokeWidth={0.8} />
      ))}
      {numbered.map((mark) => {
        const moved = Math.hypot(mark.x - mark.home[0], mark.y - mark.home[1]) > PIN_R * 0.6;
        return moved ? (
          <g key={`l-${mark.n}`}>
            <line x1={mark.home[0]} y1={mark.home[1]} x2={mark.x} y2={mark.y} {...paint("leader")} />
            <circle cx={mark.home[0]} cy={mark.home[1]} r={1.8} {...paint("pinMain")} strokeWidth={0} />
          </g>
        ) : null;
      })}
      {numbered.map((mark) => (
        <g key={`p-${mark.n}`}>
          <circle cx={mark.x} cy={mark.y} r={PIN_R} {...paint(mark.main ? "pinMain" : "pinSide")} />
          <text x={mark.x} y={mark.y + 3.2} textAnchor="middle" fontSize={mark.n >= 10 ? 8 : 9} {...paint(mark.main ? "pinMainText" : "pinSideText")}>
            {mark.n}
          </text>
        </g>
      ))}
    </g>
  );
}

function SiteMark({ at, tag, label, paint }: { at: [number, number]; tag: Box; label: string; paint: Paint }) {
  const [x, y] = at;
  return (
    <g>
      <line x1={x - 20} y1={y} x2={x + 20} y2={y} {...paint("cross")} />
      <line x1={x} y1={y - 20} x2={x} y2={y + 20} {...paint("cross")} />
      <rect x={x - 8} y={y - 8} width={16} height={16} {...paint("siteRing")} />
      <rect x={x - 6} y={y - 6} width={12} height={12} {...paint("siteFill")} />
      <rect x={tag.x} y={tag.y} width={tag.width} height={tag.height} rx={7} {...paint("tag")} />
      <text x={tag.x + tag.width / 2} y={tag.y + 10} textAnchor="middle" fontSize={8} letterSpacing={0.6} {...paint("tagText")}>
        {label}
      </text>
    </g>
  );
}

function Scale({ frame, paint }: { frame: Frame; paint: Paint }) {
  const bar = scaleBar(frame, Math.min(110, frame.width * 0.22));
  const right = frame.width - 12;
  const left = right - bar.length;
  const y = frame.height - 12;
  return (
    <g aria-hidden="true">
      <path d={`M${left} ${y - 4}V${y}H${right}V${y - 4}`} {...paint("scale")} fill="none" strokeWidth={1.2} />
      <text x={right} y={y - 7} textAnchor="end" fontSize={8} {...paint("scaleText")}>
        {bar.label}
      </text>
      <g transform={`translate(${right - 6} ${y - 34})`}>
        <path d="M0 -9L4 4L0 1.5L-4 4Z" {...paint("scale")} strokeWidth={0.5} />
        <text y={14} textAnchor="middle" fontSize={8} {...paint("scaleText")}>
          N
        </text>
      </g>
    </g>
  );
}

interface ArtProps {
  drawn: Drawn;
  paint: Paint;
  clipId: string;
  siteLabel: string;
  /** The street map's credit, or why there is none. */
  note: string;
  named: boolean;
}

/** One map: land, water, parks, the area, streets by rank, pins, trips, the site, the scale and the credit. */
function MapArt({ drawn, paint, clipId, siteLabel, note, named }: ArtProps) {
  const { frame, edge } = drawn;
  const { width, height } = frame;
  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <rect width={width} height={height} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <rect width={width} height={height} {...paint(edge ? "beyond" : "land")} />
        {edge ? <rect x={edge.x} y={edge.y} width={edge.width} height={edge.height} {...paint("land")} /> : null}
        {drawn.water ? <path d={drawn.water} fillRule="nonzero" {...paint("water")} /> : null}
        {drawn.parks ? <path d={drawn.parks} {...paint("park")} /> : null}
        <path d={drawn.walk} {...paint("walkFill")} />
        {STREET_LAYERS.map((layer) =>
          drawn.streets[layer] ? (
            <path key={`c-${layer}`} d={drawn.streets[layer]} {...paint("casing")} strokeWidth={STREET_WIDTH[layer][0]} strokeLinecap="round" strokeLinejoin="round" />
          ) : null,
        )}
        {STREET_LAYERS.map((layer) =>
          drawn.streets[layer] ? (
            <path key={`s-${layer}`} d={drawn.streets[layer]} {...paint("street")} strokeWidth={STREET_WIDTH[layer][1]} strokeLinecap="round" strokeLinejoin="round" />
          ) : null,
        )}
        {edge ? <rect x={edge.x} y={edge.y} width={edge.width} height={edge.height} {...paint("edge")} /> : null}
        <path d={drawn.walk} {...paint("walkLine")} strokeLinejoin="round" />
        <Pins marks={drawn.pins} paint={paint} />
        <SiteMark at={frame.site} tag={drawn.tag} label={siteLabel} paint={paint} />
        <Trips marks={drawn.trips} paint={paint} named={named} />
        <Scale frame={frame} paint={paint} />
        <text x={10} y={height - 9} fontSize={7.5} {...paint("note")}>
          {note}
        </text>
      </g>
    </g>
  );
}

const noteOf = (streets: StreetMap | null) => (streets ? streets.credit : "Street map unavailable");

// ---------- The report's cover ----------

/** The cover map's size on paper, in frame units: 480 wide fills two thirds of the report's 174 mm text block. */
const PRINT_SIZE = { width: 480, height: 330 };

function frameHeight(width: number): number {
  return Math.round(width / (width < 420 ? 1.1 : 1.33));
}

/** Follows the frame's width on screen, so labels keep their size on a phone. */
function useWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(PRINT_SIZE.width);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.width ?? 0);
      if (next > 0) setWidth(Math.max(280, next));
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [ref, width];
}

interface SiteMapProps {
  /** The cover's map (lib/sitemap coverMapOf); null for a kit made before maps. */
  map: CoverMap | null;
  /** The survey area's outline, [lat, lon]. */
  ring: LatLon[];
  site: LatLon;
  /** The area in words: the cover's area_label, "10-minute walk", "30-minute drive", "25 km drive". */
  area: string;
}

/** The report cover's map: the street map around the survey's area, the places of the kind inside it with the numbers
    the survey and the competition table give them, and where people here go for it now, with the claim in one line. */
export function SiteMap({ map, ring, site, area }: SiteMapProps) {
  const [frameRef, width] = useWidth();
  const id = useId().replace(/[^\w-]/g, "");
  const streets = map?.streets ?? null;
  const pins = useMemo(() => map?.pins ?? [], [map]);
  const trips = useMemo<TripInput[]>(() => (map?.trips ?? []).map((trip) => ({ key: trip.key, km: trip.km, point: [trip.lat, trip.lon] })), [map]);
  const height = frameHeight(width);
  const screen = useMemo(() => lay(streets, ring, site, width, height, pins, trips), [streets, ring, site, width, height, pins, trips]);
  const paper = useMemo(
    () => lay(streets, ring, site, PRINT_SIZE.width, PRINT_SIZE.height, pins, trips),
    [streets, ring, site, pins, trips],
  );
  const where = area;
  const caption = map?.caption ?? `The ${where} around the site`;
  const numbered = pins.flatMap((pin) => (pin.n === null ? [] : [{ ...pin, n: pin.n }])).sort((a, b) => a.n - b.n);
  const dots = pins.length - numbered.length;
  const label = `${caption}. Map of the ${where} around the site${streets ? "" : "; street map unavailable"}.`;
  return (
    <div className="site-map">
      <div className="sm-frame" ref={frameRef}>
        <svg className="sm-svg sm-screen" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
          <MapArt drawn={screen} paint={classPaint} clipId={`${id}-s`} siteLabel="SITE" note={noteOf(streets)} named />
        </svg>
        <svg className="sm-svg sm-paper" viewBox={`0 0 ${PRINT_SIZE.width} ${PRINT_SIZE.height}`} aria-hidden="true">
          <MapArt drawn={paper} paint={classPaint} clipId={`${id}-p`} siteLabel="SITE" note={noteOf(streets)} named />
        </svg>
      </div>
      <p className="sm-caption">{caption}</p>
      {numbered.length || dots || trips.length ? (
        <div className="sm-key">
          {numbered.length || dots ? (
            <div className="sm-key-part">
              <p className="sm-key-head mono">{`Inside the ${where}`}</p>
              {numbered.length ? (
                <ol className="sm-key-list">
                  {numbered.map((pin) => (
                    <li key={pin.n}>
                      <span className={pin.main ? "sm-badge sm-badge-main" : "sm-badge"} aria-hidden="true">
                        {pin.n}
                      </span>
                      <span className="sr-only">{pin.n}. </span>
                      <span className="sm-key-name">{pin.name}</span>
                    </li>
                  ))}
                </ol>
              ) : null}
              {dots ? (
                <p className="sm-key-more">
                  {numbered.length
                    ? `${dots} more as dots: the competition table lists them all.`
                    : `${dots} as dots: the competition table lists them all.`}
                </p>
              ) : null}
            </div>
          ) : null}
          {map?.trips.length ? (
            <div className="sm-key-part">
              <p className="sm-key-head mono">Where people here go now</p>
              <ol className="sm-key-list">
                {map.trips.map((trip) => (
                  <li key={trip.key}>
                    <span className="sm-badge sm-badge-trip" aria-hidden="true">
                      {trip.key}
                    </span>
                    <span className="sr-only">{trip.key}. </span>
                    <span className="sm-key-name">{trip.name}</span>
                    <span className="sm-km">{trip.km} km</span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------- The window poster ----------

interface PosterSiteMapProps {
  map: PosterMap | null;
  ring: LatLon[];
  site: LatLon;
  width: number;
  height: number;
  /** Where the poster sets its own words over the map, for the trips' flags to keep clear of. */
  keepClear?: Box[];
}

/** The poster's map as SVG shapes for its map frame: the same map without a name on it, in the poster's own ink. The
    trips carry the poster's argument as flags with their distance; an ad never names another business. */
export function PosterSiteMap({ map, ring, site, width, height, keepClear }: PosterSiteMapProps) {
  const id = useId().replace(/[^\w-]/g, "");
  const streets = map?.streets ?? null;
  const drawn = useMemo(() => {
    const trips = (map?.trips ?? []).map((trip): TripInput => ({ key: null, km: trip.km, point: tripPoint(site, trip) }));
    return lay(streets, ring, site, width, height, [], trips, keepClear, "YOU ARE HERE");
  }, [map, streets, ring, site, width, height, keepClear]);
  return <MapArt drawn={drawn} paint={printPaint} clipId={`${id}-m`} siteLabel="YOU ARE HERE" note={noteOf(streets)} named={false} />;
}
