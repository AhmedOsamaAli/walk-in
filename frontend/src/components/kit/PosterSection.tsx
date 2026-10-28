import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { paypalOf, type KitCampaign } from "../../api/founders";
import type { KitPoster } from "../../api/kit";
import { inSandbox, posterLine } from "../../lib/founders";
import { absoluteUrl, LINK_KINDS, shortLink } from "../../lib/kit";
import { isPlainClick } from "../../lib/navigation";
import { useSession } from "../../state/session";
import { SandboxNotice } from "../founders/SandboxNotice";
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
  /** The viewer's own open Founders campaign for the kit: the QR code opens it, and the poster says its terms. */
  campaign: KitCampaign | null;
  /** Takes the owner to the field for their link, in the kit's Links tab, with the cursor in it. */
  onAddLink: () => void;
}

/**
 * The poster on screen, printed on its own (the page's print styles hide everything else), or saved as an SVG file. Its
 * QR code needs a page to send a passer-by to: the owner's open Founders campaign, else a page of the owner's own;
 * without either, the poster has none and asks for the link.
 */
export function PosterSection({ poster, link, landing, campaign, onAddLink }: PosterSectionProps) {
  const svg = useRef<SVGSVGElement>(null);
  const [printing, setPrinting] = useState(false);
  const { config } = useSession();
  const own = landing.kind === "own" ? landing : null;
  const code = campaign ? absoluteUrl(campaign.url) : own ? link : null;
  const back = campaign ? posterLine(campaign.amount, campaign.goal, campaign.deadline) : null;

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
        <PosterArt poster={poster} link={code} back={back} svgRef={svg} />
      </figure>
      <div className="poster-side">
        {own || campaign ? null : (
          <div className="poster-ask" role="note">
            <p>
              <b>No QR code yet.</b> A QR code needs somewhere useful to send a passer-by: your website, an Instagram or
              Facebook page, a Google Maps listing or a WhatsApp link. Add yours and the poster carries one; until then it
              prints without.
            </p>
            <a
              className="ghost mono"
              href="#links"
              onClick={(event) => {
                // A modified click opens the kit on its Links tab elsewhere, as a link does.
                if (!isPlainClick(event)) return;
                event.preventDefault();
                onAddLink();
              }}
            >
              Add your link <span aria-hidden="true">→</span>
            </a>
          </div>
        )}
        <p className="poster-side-lead">
          A sheet for the window, set from the kit&apos;s checked lines and drawn on the streets around the door: the people who
          pass it are the people it is about.
          {campaign ? " Its QR code opens your Founders campaign, so a passer-by can back it on the spot." : ""}
        </p>
        {campaign && inSandbox(paypalOf(config)) ? <SandboxNotice /> : null}
        <dl className="spec poster-spec">
          {campaign && code ? (
            <div>
              <dt>QR code opens</dt>
              <dd>
                <span className="poster-link">{shortLink(code)}</span>
                <small className="spec-basis">
                  Your Founders campaign, where neighbors pledge with PayPal. The line beside the code is its own terms.
                </small>
              </dd>
            </div>
          ) : own && code ? (
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
              <PosterArt poster={poster} link={code} back={back} />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}