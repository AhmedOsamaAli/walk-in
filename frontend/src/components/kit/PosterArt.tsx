import { useEffect, useId, useMemo, useState, type Ref } from "react";
import type { KitPoster } from "../../api/kit";
import { scanCaption } from "../../lib/kit";
import { BACK_PAD, BACK_SIZE, layoutPoster, POSTER_H, POSTER_M, POSTER_W, posterAreaLine, roughMeasure, type Face, type Measure } from "../../lib/poster";
import { qrPath } from "../../lib/qr";
import { posterMapOf } from "../../lib/sitemap";
import { PosterSiteMap } from "./SiteMap";

// A printed sheet keeps its own colors whatever the screen's theme: ink, highlighter yellow and the blue pen on paper.
const INK = "#1d1d1f";
const PAPER = "#fbfaf6";
const YELLOW = "#ffcb00";
const BLUE = "#0f68ea";
const ASH = "#5f5f59";
// The map's land, which the labels set over it are haloed in so streets never cross them.
const LAND = "#f3f1ea";
const FONTS: Record<Face, string> = {
  serif: '"Newsreader Variable", Newsreader, Georgia, "Times New Roman", serif',
  sans: '"Geist Variable", Geist, Inter, system-ui, -apple-system, "Segoe UI", sans-serif',
  mono: '"Geist Mono Variable", "Geist Mono", ui-monospace, Menlo, Consolas, monospace',
};
const INNER = POSTER_W - 2 * POSTER_M;

/** Set once the poster's typefaces have loaded, so a poster drawn later (the print copy) measures right away. */
let fontsLoaded = false;

/** Measures with the page's own fonts once they have loaded, and from character counts until then. */
function useMeasure(): Measure {
  const [ready, setReady] = useState(fontsLoaded);
  useEffect(() => {
    if (ready) return;
    let live = true;
    const fonts = document.fonts;
    void Promise.all([
      fonts.load(`400 40px ${FONTS.serif}`),
      fonts.load(`italic 400 40px ${FONTS.serif}`),
      fonts.load(`400 18px ${FONTS.sans}`),
      fonts.load(`500 11px ${FONTS.mono}`),
    ])
      .catch(() => undefined)
      .then(() => {
        fontsLoaded = true;
        if (live) setReady(true);
      });
    return () => {
      live = false;
    };
  }, [ready]);
  return useMemo<Measure>(() => {
    const context = ready ? document.createElement("canvas").getContext("2d") : null;
    if (!context) return roughMeasure;
    return (text, face, size, italic = false) => {
      context.font = `${italic ? "italic " : ""}${face === "mono" ? 500 : 400} ${size}px ${FONTS[face]}`;
      return context.measureText(text).width;
    };
  }, [ready]);
}

interface PosterArtProps {
  poster: KitPoster;
  /** The poster's tracked link to the owner's own page, drawn as the QR code; null prints the poster without one. */
  link: string | null;
  /** The owner's open Founders campaign, in a line from its terms: set beside the QR code, which then opens it. */
  back?: string | null;
  svgRef?: Ref<SVGSVGElement>;
}

/** A label set over the map, haloed in the map's land so no street crosses it. */
function Halo({ x, y, size, fill, text }: { x: number; y: number; size: number; fill: string; text: string }) {
  return (
    <text
      x={x}
      y={y}
      fontFamily={FONTS.mono}
      fontSize={size}
      fontWeight="500"
      letterSpacing="1.4"
      fill={fill}
      stroke={LAND}
      strokeWidth="4"
      strokeLinejoin="round"
      paintOrder="stroke"
    >
      {text}
    </text>
  );
}

/** The window poster as vector art: the name, the claim the evidence allows, the street map around the survey's area
 * (where people here go now, when the plan may say so) and, when the owner gave a link of their own, a QR code to it.
 * With the owner's open Founders campaign, the QR code opens the campaign and the campaign's terms sit beside it. */
export function PosterArt({ poster, link, back = null, svgRef }: PosterArtProps) {
  const measure = useMeasure();
  const id = useId().replace(/[^\w-]/g, "");
  const layout = useMemo(
    () =>
      layoutPoster(
        {
          name: poster.name,
          tagline: poster.tagline,
          headline: poster.headline,
          subline: poster.subline,
          hours: poster.hours,
          proof: poster.claim?.proof ?? null,
          back,
        },
        measure,
        { qr: link !== null },
      ),
    [poster, measure, link, back],
  );
  const map = useMemo(() => posterMapOf(poster), [poster]);
  const code = useMemo(() => (link ? qrPath(link) : null), [link]);
  const hood = poster.neighborhoods[0] ?? "";
  const { qr, hoursBox } = layout;
  const quiet = 10;
  // Set with 0.8 units between letters, which the measure leaves out.
  const caption =
    link && qr
      ? back
        ? "SCAN TO BACK IT"
        : scanCaption(link, qr.size + 20, (line) => measure(line, "mono", 9) + 0.8 * line.length)
      : null;
  const label = [poster.name, poster.headline, back ?? poster.subline].filter(Boolean).join(". ");
  // The map's own words, set over it: who the area holds, and where people here go now when the plan may say so.
  const areaLine = posterAreaLine(poster.area_label ?? `${poster.minutes}-minute walk`);
  const areaWidth = measure(areaLine, "mono", 10.5) + 1.4 * areaLine.length;
  const argument = map?.caption?.toUpperCase() ?? null;
  const argumentWidth = argument ? measure(argument, "mono", 10) + 1.2 * argument.length : 0;
  const mapHeight = layout.map.height;
  const keepClear = useMemo(
    () => [
      { x: 8, y: 10, width: areaWidth + 16, height: 22 },
      ...(argumentWidth ? [{ x: 8, y: mapHeight - 42, width: argumentWidth + 18, height: 24 }] : []),
    ],
    [areaWidth, argumentWidth, mapHeight],
  );

  return (
    <svg
      ref={svgRef}
      className="poster-art"
      viewBox={`0 0 ${POSTER_W} ${POSTER_H}`}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-labelledby={`${id}-title`}
    >
      <title id={`${id}-title`}>{`Window poster: ${label}`}</title>
      <defs>
        <clipPath id={`${id}-map`}>
          <rect width={INNER} height={layout.map.height} rx="14" />
        </clipPath>
      </defs>
      <rect width={POSTER_W} height={POSTER_H} fill={PAPER} />
      <rect x="14" y="14" width={POSTER_W - 28} height={POSTER_H - 28} fill="none" stroke={INK} strokeWidth="1.2" />

      <text x={POSTER_M} y="58" fontFamily={FONTS.mono} fontSize="11.5" fontWeight="500" letterSpacing="2.2" fill={INK}>
        NEW ON THE BLOCK
      </text>
      {hood ? (
        <text x={POSTER_W - POSTER_M} y="58" textAnchor="end" fontFamily={FONTS.mono} fontSize="11.5" fontWeight="500" letterSpacing="2.2" fill={BLUE}>
          {hood.toUpperCase()}
        </text>
      ) : null}
      <rect x={POSTER_M} y="68" width={INNER} height="2.5" fill={INK} />

      {layout.name.lines.map((line, index) => (
        <text key={line} x={POSTER_M - 2} y={layout.name.y[index]} fontFamily={FONTS.serif} fontSize={layout.name.size} fill={INK}>
          {line}
        </text>
      ))}
      {layout.tagline?.lines.map((line, index) => (
        <text key={line} x={POSTER_M} y={layout.tagline?.y[index]} fontFamily={FONTS.serif} fontStyle="italic" fontSize={layout.tagline?.size} fill={INK}>
          {line}
        </text>
      ))}
      {layout.headline?.lines.map((line, index) => {
        const block = layout.headline;
        if (!block) return null;
        const baseline = block.y[index] ?? 0;
        return (
          <g key={line}>
            <rect x={POSTER_M - 4} y={baseline - block.size * 0.4} width={(block.widths[index] ?? 0) + 8} height={block.size * 0.5} fill={YELLOW} />
            <text x={POSTER_M} y={baseline} fontFamily={FONTS.serif} fontStyle="italic" fontSize={block.size} fill={INK}>
              {line}
            </text>
          </g>
        );
      })}

      <g transform={`translate(${POSTER_M} ${layout.map.y})`}>
        <g clipPath={`url(#${id}-map)`}>
          <PosterSiteMap map={map} ring={poster.ring} site={poster.site} width={INNER} height={layout.map.height} keepClear={keepClear} />
        </g>
        <rect width={INNER} height={layout.map.height} rx="14" fill="none" stroke={INK} strokeWidth="1.4" />
        <Halo x={16} y={26} size={10.5} fill={INK} text={areaLine} />
        {argument ? (
          <g>
            <rect x={12} y={layout.map.height - 38} width={argumentWidth + 10} height={17} rx="3" fill={YELLOW} stroke={INK} strokeWidth="0.8" />
            <text x={17} y={layout.map.height - 26} fontFamily={FONTS.mono} fontSize="10" fontWeight="600" letterSpacing="1.2" fill={INK}>
              {argument}
            </text>
          </g>
        ) : poster.neighborhoods.length ? (
          <Halo x={16} y={layout.map.height - 24} size={9.5} fill={ASH} text={poster.neighborhoods.slice(0, 3).join(" · ").toUpperCase()} />
        ) : null}
      </g>

      <rect x={POSTER_M} y={layout.bandTop} width={INNER} height="1.4" fill={INK} />
      {layout.back ? (
        <g>
          <rect
            x={layout.back.box.x}
            y={layout.back.box.y}
            width={layout.back.box.width}
            height={layout.back.box.height}
            rx="10"
            fill={YELLOW}
            stroke={INK}
            strokeWidth="1.3"
          />
          {layout.back.text.lines.map((line, index) => (
            <text
              key={line}
              x={(layout.back?.box.x ?? POSTER_M) + BACK_PAD}
              y={layout.back?.text.y[index]}
              fontFamily={FONTS.sans}
              fontSize={BACK_SIZE}
              fontWeight="500"
              fill={INK}
            >
              {line}
            </text>
          ))}
        </g>
      ) : null}
      {layout.subline?.lines.map((line, index) => (
        <text key={line} x={POSTER_M} y={layout.subline?.y[index]} fontFamily={FONTS.sans} fontSize={layout.subline?.size} fill={INK}>
          {line}
        </text>
      ))}
      {layout.hours && layout.hoursLabelY !== null ? (
        <>
          {hoursBox ? (
            <rect x={hoursBox.x} y={hoursBox.y} width={hoursBox.width} height={hoursBox.height} rx="10" fill="#ffffff" stroke={INK} strokeWidth="1.3" />
          ) : null}
          <text x={layout.hoursX} y={layout.hoursLabelY} fontFamily={FONTS.mono} fontSize="9.5" fontWeight="500" letterSpacing="1.6" fill={BLUE}>
            OPEN
          </text>
          {layout.hours.lines.map((line, index) => (
            <text key={line} x={layout.hoursX} y={layout.hours?.y[index]} fontFamily={FONTS.sans} fontSize={layout.hours?.size} fill={INK}>
              {line}
            </text>
          ))}
        </>
      ) : null}

      {qr && code ? (
        <g transform={`translate(${qr.x} ${qr.y})`}>
          <rect width={qr.size} height={qr.size} rx="10" fill="#ffffff" stroke={INK} strokeWidth="1.3" />
          <path
            d={code.path}
            transform={`translate(${quiet} ${quiet}) scale(${(qr.size - 2 * quiet) / code.size})`}
            fill={INK}
            shapeRendering="crispEdges"
          />
        </g>
      ) : null}
      {qr && caption ? (
        <text x={qr.x + qr.size / 2} y={qr.y - 9} textAnchor="middle" fontFamily={FONTS.mono} fontSize="9" fontWeight="500" letterSpacing="0.8" fill={INK}>
          {caption}
        </text>
      ) : null}

      {layout.proof?.lines.map((line, index) => (
        <text key={line} x={POSTER_M} y={layout.proof?.y[index]} fontFamily={FONTS.mono} fontSize={layout.proof?.size} fill={ASH}>
          {line}
        </text>
      ))}
    </svg>
  );
}
