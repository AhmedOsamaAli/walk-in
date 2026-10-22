import { useEffect, useId, useMemo, useState, type Ref } from "react";
import type { KitPoster } from "../../api/kit";
import { fitWalk, qrPath, shortLink } from "../../lib/kit";
import { fitLines, layoutPoster, POSTER_H, POSTER_M, POSTER_W, roughMeasure, type Face, type Measure } from "../../lib/poster";

// A printed sheet keeps its own colors whatever the screen's theme: ink, highlighter yellow and the blue pen on paper.
const INK = "#1d1d1f";
const PAPER = "#fbfaf6";
const YELLOW = "#ffcb00";
const BLUE = "#0f68ea";
const WASH = "#e8effc";
const ASH = "#5f5f59";
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
  /** The poster's tracked link, drawn as the QR code; null until there is a page for it to open. */
  link: string | null;
  svgRef?: Ref<SVGSVGElement>;
}

/** The window poster as vector art: the name, the claim the evidence allows, the walk's real outline and a QR code. */
export function PosterArt({ poster, link, svgRef }: PosterArtProps) {
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
        },
        measure,
      ),
    [poster, measure],
  );
  const walk = useMemo(() => fitWalk(poster.ring, poster.site, INNER, layout.map.height, 40), [poster, layout.map.height]);
  const code = useMemo(() => (link ? qrPath(link) : null), [link]);
  const hood = poster.neighborhoods[0] ?? "";
  const { qr } = layout;
  const quiet = 10;
  const caption = link ? fitLines(`SCAN · ${shortLink(link).toUpperCase()}`, qr.size + 24, (line) => measure(line, "mono", 9), 1)[0] : null;
  const label = [poster.name, poster.headline, poster.subline].filter(Boolean).join(". ");

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
        <pattern id={`${id}-grid`} width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M24 0H0V24" fill="none" stroke={BLUE} strokeOpacity="0.09" strokeWidth="1" />
        </pattern>
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
        <rect width={INNER} height={layout.map.height} rx="14" fill={WASH} />
        <g clipPath={`url(#${id}-map)`}>
          <rect width={INNER} height={layout.map.height} fill={`url(#${id}-grid)`} />
          {walk.path ? (
            <path d={walk.path} fill={BLUE} fillOpacity="0.13" stroke={BLUE} strokeWidth="2.6" strokeLinejoin="round" />
          ) : null}
        </g>
        <rect width={INNER} height={layout.map.height} rx="14" fill="none" stroke={INK} strokeWidth="1.4" />
        <g transform={`translate(${walk.site[0]} ${walk.site[1]})`}>
          <circle r="22" fill={YELLOW} fillOpacity="0.45" />
          <rect x="-7" y="-19" width="14" height="19" fill={BLUE} stroke={INK} strokeWidth="1.5" />
          <rect x="-4.6" y="-16.4" width="9.2" height="6.4" fill="#ffffff" fillOpacity="0.55" />
          <circle cx="-3.8" cy="-8.2" r="1.2" fill={YELLOW} />
          <path d="M-16 0H16" stroke={INK} strokeWidth="1.8" strokeLinecap="round" />
          <text x="22" y="-6" fontFamily={FONTS.mono} fontSize="10" fontWeight="500" letterSpacing="1.4" fill={INK}>
            YOU ARE HERE
          </text>
        </g>
        <text x="18" y="28" fontFamily={FONTS.mono} fontSize="10.5" fontWeight="500" letterSpacing="1.6" fill={INK}>
          {`EVERYONE INSIDE THE BLUE LINE IS A ${poster.minutes}-MINUTE WALK AWAY`}
        </text>
        {poster.neighborhoods.length ? (
          <text x="18" y={layout.map.height - 18} fontFamily={FONTS.mono} fontSize="9.5" letterSpacing="1.2" fill={ASH}>
            {poster.neighborhoods.slice(0, 3).join(" · ").toUpperCase()}
          </text>
        ) : null}
        <g transform={`translate(${INNER - 26} ${layout.map.height - 34})`} aria-hidden="true">
          <path d="M0 -12L5 4L0 1L-5 4Z" fill={INK} />
          <text y="17" textAnchor="middle" fontFamily={FONTS.mono} fontSize="9" fontWeight="500" fill={INK}>
            N
          </text>
        </g>
      </g>

      <rect x={POSTER_M} y={layout.bandTop} width={INNER} height="1.4" fill={INK} />
      {layout.subline?.lines.map((line, index) => (
        <text key={line} x={POSTER_M} y={layout.subline?.y[index]} fontFamily={FONTS.sans} fontSize={layout.subline?.size} fill={INK}>
          {line}
        </text>
      ))}
      {layout.hours && layout.hoursLabelY !== null ? (
        <>
          <text x={POSTER_M} y={layout.hoursLabelY} fontFamily={FONTS.mono} fontSize="9.5" fontWeight="500" letterSpacing="1.6" fill={BLUE}>
            OPEN
          </text>
          {layout.hours.lines.map((line, index) => (
            <text key={line} x={POSTER_M} y={layout.hours?.y[index]} fontFamily={FONTS.sans} fontSize={layout.hours?.size} fill={INK}>
              {line}
            </text>
          ))}
        </>
      ) : null}

      <g transform={`translate(${qr.x} ${qr.y})`}>
        <rect width={qr.size} height={qr.size} rx="10" fill="#ffffff" stroke={INK} strokeWidth="1.3" />
        {code ? (
          <path
            d={code.path}
            transform={`translate(${quiet} ${quiet}) scale(${(qr.size - 2 * quiet) / code.size})`}
            fill={INK}
            shapeRendering="crispEdges"
          />
        ) : (
          <>
            <rect x="12" y="12" width={qr.size - 24} height={qr.size - 24} rx="6" fill="none" stroke={ASH} strokeDasharray="4 4" />
            <text x={qr.size / 2} y={qr.size / 2 - 4} textAnchor="middle" fontFamily={FONTS.mono} fontSize="9" letterSpacing="1" fill={ASH}>
              QR CODE
            </text>
            <text x={qr.size / 2} y={qr.size / 2 + 10} textAnchor="middle" fontFamily={FONTS.mono} fontSize="8" letterSpacing="0.6" fill={ASH}>
              ADD A LANDING PAGE
            </text>
          </>
        )}
      </g>
      {caption ? (
        <text x={qr.x + qr.size / 2} y={qr.y + qr.size + 17} textAnchor="middle" fontFamily={FONTS.mono} fontSize="9" fontWeight="500" letterSpacing="0.8" fill={INK}>
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
