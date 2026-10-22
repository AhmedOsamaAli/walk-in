import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { KitPoster } from "../../api/kit";
import { shortLink } from "../../lib/kit";
import type { Landing } from "./TrackedLinks";
import { PosterArt } from "./PosterArt";

/** "golden-hour-poster.svg". */
function fileName(name: string): string {
  const slug = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${slug || "walk-in"}-poster.svg`;
}

function download(svg: SVGSVGElement, name: string): void {
  const text = `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(svg)}`;
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName(name);
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 2000);
}

interface PosterSectionProps {
  poster: KitPoster;
  /** The poster's tracked link, for the QR code. */
  link: string | null;
  landing: Landing;
}

/** The poster on screen, printed on its own (the page's print styles hide everything else), or saved as an SVG file. */
export function PosterSection({ poster, link, landing }: PosterSectionProps) {
  const svg = useRef<SVGSVGElement>(null);
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    if (!printing) return;
    const root = document.documentElement;
    root.dataset.print = "poster";
    const done = () => {
      setPrinting(false);
    };
    window.addEventListener("afterprint", done);
    window.print();
    return () => {
      window.removeEventListener("afterprint", done);
      delete root.dataset.print;
    };
  }, [printing]);

  return (
    <div className="poster-section">
      <figure className="poster-frame">
        <PosterArt poster={poster} link={link} svgRef={svg} />
      </figure>
      <div className="poster-side">
        <p className="poster-side-lead">
          A sheet for the window, set from the kit&apos;s checked lines and drawn from the walk&apos;s real outline: the people who
          pass it are the people it is about.
        </p>
        <dl className="spec poster-spec">
          <div>
            <dt>QR code opens</dt>
            <dd>
              {link ? <span className="poster-link">{shortLink(link)}</span> : "Nothing yet"}
              <small className="spec-basis">
                {landing.kind === "website"
                  ? "Your website, tagged as the poster channel."
                  : landing.kind === "campaign"
                    ? "Your founding-supporter page, tagged as the poster channel."
                    : "This concept in the survey, tagged as the poster channel. Add your website below to change it."}
              </small>
            </dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>A4 or US Letter, portrait. Print at 100% for a sharp QR code.</dd>
          </div>
        </dl>
        <div className="poster-actions">
          <button
            type="button"
            className="ink-button"
            onClick={() => {
              setPrinting(true);
            }}
          >
            Print the poster
          </button>
          <button
            type="button"
            className="ghost mono"
            onClick={() => {
              if (svg.current) download(svg.current, poster.name);
            }}
          >
            Download SVG
          </button>
        </div>
        <p className="poster-tip mono">Print, then “Save as PDF”, keeps the page&apos;s typefaces; the SVG uses your own.</p>
      </div>
      {printing
        ? createPortal(
            <div className="print-only print-poster">
              <PosterArt poster={poster} link={link} />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
