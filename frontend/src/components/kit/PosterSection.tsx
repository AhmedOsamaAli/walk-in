import { useEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import type { KitPoster } from "../../api/kit";
import { LINK_KINDS, shortLink } from "../../lib/kit";
import { OWN_LINK_ID, type Landing } from "./TrackedLinks";
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

/** Takes the owner to the field for their link, below, and puts the cursor in it. */
function toLinkField(event: MouseEvent<HTMLAnchorElement>): void {
  const field = document.getElementById(OWN_LINK_ID);
  if (!field) return;
  event.preventDefault();
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  field.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
  field.focus({ preventScroll: true });
}

/**
 * The poster on screen, printed on its own (the page's print styles hide everything else), or saved as an SVG file. Its
 * QR code needs a page of the owner's to send a passer-by to: without one, the poster has none and asks for the link.
 */
export function PosterSection({ poster, link, landing }: PosterSectionProps) {
  const svg = useRef<SVGSVGElement>(null);
  const [printing, setPrinting] = useState(false);
  const own = landing.kind === "own" ? landing : null;
  const code = own ? link : null;

  useEffect(() => {
    if (!printing) return;
    const root = document.documentElement;
    root.dataset.print = "poster";
    let live = true;
    const done = () => {
      setPrinting(false);
    };
    window.addEventListener("afterprint", done);
    // The print copy is set in the page's typefaces: wait for them, or the sheet prints in a fallback.
    void document.fonts.ready.then(() => {
      if (live) window.print();
    });
    return () => {
      live = false;
      window.removeEventListener("afterprint", done);
      delete root.dataset.print;
    };
  }, [printing]);

  return (
    <div className="poster-section">
      <figure className="poster-frame">
        <PosterArt poster={poster} link={code} svgRef={svg} />
      </figure>
      <div className="poster-side">
        {own ? null : (
          <div className="poster-ask" role="note">
            <p>
              <b>No QR code yet.</b> A QR code needs somewhere useful to send a passer-by: your website, an Instagram or
              Facebook page, a Google Maps listing or a WhatsApp link. Add yours and the poster carries one; until then it
              prints without.
            </p>
            <a className="ghost mono" href={`#${OWN_LINK_ID}`} onClick={toLinkField}>
              Add your link <span aria-hidden="true">↓</span>
            </a>
          </div>
        )}
        <p className="poster-side-lead">
          A sheet for the window, set from the kit&apos;s checked lines and drawn on the streets around the door: the people who
          pass it are the people it is about.
        </p>
        <dl className="spec poster-spec">
          {own && code ? (
            <div>
              <dt>QR code opens</dt>
              <dd>
                <span className="poster-link">{shortLink(code)}</span>
                <small className="spec-basis">
                  {`${LINK_KINDS[own.page].page.charAt(0).toUpperCase()}${LINK_KINDS[own.page].page.slice(1)}, tagged as the poster's channel.`}
                </small>
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Paper</dt>
            <dd>
              {code ? "One page of A4 or US Letter, portrait, with the QR code about 4 cm wide." : "One page of A4 or US Letter, portrait."}
              <small className="spec-basis">
                {code ? "Print at 100% (the default scale) so the code scans from across the pavement." : "Print at 100% (the default scale)."}
              </small>
            </dd>
          </div>
        </dl>
        <div className="poster-actions">
          <button
            type="button"
            className="ink-button"
            onClick={() => {
              // The print copy is already out when a browser never said the last print ended.
              if (printing) window.print();
              else setPrinting(true);
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
        <p className="poster-tip">
          To keep a PDF, print it and choose “Save as PDF”: that keeps the page&apos;s typefaces, where the SVG uses your own.
        </p>
      </div>
      {printing
        ? createPortal(
            <div className="print-only print-poster" aria-hidden="true">
              <PosterArt poster={poster} link={code} />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}