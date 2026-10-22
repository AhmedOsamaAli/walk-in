import { useId, useRef, useState } from "react";
import type { KitLink } from "../../api/kit";
import { absoluteUrl, trackedUrl, websiteUrl } from "../../lib/commerce";
import { CopyButton } from "../CopyButton";

const KEY = "walk-in-site:";

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
    // Private browsing can refuse storage; the website then lasts for this visit.
  }
}

/** Where the tracked links land: the owner's website, else their pledge page, else the survey with the concept open. */
export interface Landing {
  url: string;
  kind: "website" | "campaign" | "survey";
}

/** The owner's website for this kit, remembered in this browser, and the landing page it makes. */
export function useLanding(token: string, campaignUrl: string | null, surveyUrl: string) {
  const [website, setWebsite] = useState(() => savedWebsite(token));
  const typed = websiteUrl(website);
  const landing: Landing = typed
    ? { url: typed, kind: "website" }
    : campaignUrl
      ? { url: absoluteUrl(campaignUrl), kind: "campaign" }
      : { url: absoluteUrl(surveyUrl), kind: "survey" };
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

const LANDS: Record<Landing["kind"], string> = {
  website: "The links and the poster's QR code open your website, tagged per channel.",
  campaign: "No website yet: the links and the QR code open your founding-supporter page, tagged per channel.",
  survey: "No website yet: the links and the QR code open this concept in the survey, tagged per channel. Add your website, or start a campaign, to change that.",
};

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

/** Every channel's tagged link to the landing page, and the website they land on. */
export function TrackedLinks({ links, landing, website, invalid, onWebsite }: TrackedLinksProps) {
  const id = useId();
  const campaign = links[0]?.utm_campaign;
  return (
    <div className="links-panel">
      <label className="cf-field links-site">
        <span className="mono label">Your website</span>
        <input
          className="field-input"
          type="url"
          inputMode="url"
          autoComplete="url"
          placeholder="https://your-business.com"
          value={website}
          aria-invalid={invalid}
          aria-describedby={`${id}-lands`}
          onChange={(event) => {
            onWebsite(event.target.value);
          }}
        />
        <span className={invalid ? "cf-hint bad" : "cf-hint"} id={`${id}-lands`}>
          {invalid ? "That isn't a web address yet: try your-business.com." : LANDS[landing.kind]}
        </span>
      </label>
      <ol className="link-list">
        {links.map((link) => (
          <LinkRow key={link.key} link={link} url={trackedUrl(landing.url, link.query)} />
        ))}
      </ol>
      {campaign ? (
        <p className="links-note">
          Every link carries <code>utm_campaign={campaign}</code>: compare visits per channel in your analytics after a month,
          and move the budget to the channels that bring people in.
        </p>
      ) : null}
    </div>
  );
}
