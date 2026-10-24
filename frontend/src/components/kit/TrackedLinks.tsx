import { useId, useRef, useState } from "react";
import type { KitLink } from "../../api/kit";
import { absoluteUrl, LINK_KINDS, linkKind, trackedUrl, websiteUrl, type LinkKind } from "../../lib/kit";
import { CopyButton } from "../CopyButton";

const KEY = "walk-in-site:";
/** The field for the owner's link, which the poster's note sends them to. */
export const OWN_LINK_ID = "kit-own-link";

function savedWebsite(token: string): string {
  try {
    return window.localStorage.getItem(KEY + token) ?? "";
  } catch {
    return "";
  }
}

function saveWebsite(token: string, text: string): void {
  try {
    if (text.trim()) window.localStorage.setItem(KEY + token, text.trim());
    else window.localStorage.removeItem(KEY + token);
  } catch {
    // Private browsing can refuse storage; the link then lasts for this visit.
  }
}

/**
 * Where the tracked links land: the owner's own page, or else the survey with the concept open. The survey is no use
 * to a passer-by or an ad's audience, so the links and the poster's QR code are only shown for the owner's own page.
 */
export type Landing = { url: string; kind: "own"; page: LinkKind } | { url: string; kind: "survey" };

/** The owner's link for this kit, remembered in this browser, and the landing page it makes. */
export function useLanding(token: string, surveyUrl: string) {
  const [website, setWebsite] = useState(() => savedWebsite(token));
  const typed = websiteUrl(website);
  const landing: Landing = typed ? { url: typed, kind: "own", page: linkKind(typed) } : { url: absoluteUrl(surveyUrl), kind: "survey" };
  return {
    website,
    invalid: website.trim() !== "" && typed === null,
    landing,
    setWebsite: (text: string) => {
      setWebsite(text);
      saveWebsite(token, text);
    },
  };
}

const ASK = "A website, an Instagram or Facebook page, a Google Maps listing or a WhatsApp link. It stays in this browser.";

function LinkRow({ link, url }: { link: KitLink; url: string }) {
  const box = useRef<HTMLElement>(null);
  return (
    <li className="link-row">
      <span className="link-channel">{link.channel}</span>
      <span className="link-tags mono">
        {link.utm_source} · {link.utm_medium}
      </span>
      <code ref={box} className="link-url">
        {url}
      </code>
      <CopyButton text={url} what={`the ${link.channel} link`} target={box} />
    </li>
  );
}

interface TrackedLinksProps {
  links: KitLink[];
  landing: Landing;
  website: string;
  invalid: boolean;
  onWebsite: (text: string) => void;
}

/** The owner's link, and every channel's tagged link to it; none until there is a page of theirs to open. */
export function TrackedLinks({ links, landing, website, invalid, onWebsite }: TrackedLinksProps) {
  const id = useId();
  const tag = links[0]?.utm_campaign;
  const own = landing.kind === "own" ? landing : null;
  const kind = own ? LINK_KINDS[own.page] : null;
  return (
    <div className="links-panel">
      <label className="kit-field links-site">
        <span className="mono label">Your link</span>
        <input
          id={OWN_LINK_ID}
          className="field-input"
          type="url"
          inputMode="url"
          autoComplete="url"
          placeholder="your-business.com"
          value={website}
          aria-invalid={invalid}
          aria-describedby={`${id}-lands`}
          onChange={(event) => {
            onWebsite(event.target.value);
          }}
        />
        <span className={invalid ? "kit-hint bad" : "kit-hint"} id={`${id}-lands`}>
          {invalid
            ? "That isn't a link yet: try your-business.com or instagram.com/your-business."
            : kind
              ? `The links and the poster's QR code open ${kind.page}, tagged per channel. It stays in this browser.`
              : ASK}
        </span>
      </label>
      {own ? (
        <>
          <ol className="link-list">
            {links.map((link) => (
              <LinkRow key={link.key} link={link} url={trackedUrl(own.url, link.query)} />
            ))}
          </ol>
          {tag ? (
            <p className="links-note">
              Every link carries <code>utm_campaign={tag}</code>
              {own.page === "website"
                ? ": compare visits per channel in your analytics after a month, and move the budget to the channels that bring people in."
                : `. ${kind?.service ?? "That page"} doesn't show you these tags; a website with analytics does, so it can tell which channel brought each visit.`}
            </p>
          ) : null}
        </>
      ) : (
        <p className="links-empty">
          No tracked links yet: each one needs a page of yours to open, and so does the poster&apos;s QR code. Add your
          link above and every channel gets its own.
        </p>
      )}
    </div>
  );
}