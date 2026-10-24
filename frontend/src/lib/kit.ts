/* The launch kit's drawing and wording helpers: the channels it writes for, poster lines, the QR code, the tracked
   links and the report's paper. Pure functions, so they are tested without a browser. */
import qrcode from "qrcode-generator";
import { ApiError } from "../api/client";
import type { ChannelKey, KitStatus } from "../api/kit";
import type { LaunchPlan } from "../api/types";
import { plainError } from "./account";

export const KIT_STATUS: Record<KitStatus, string> = { building: "Building", ready: "Ready", failed: "Not built" };

/** What a kit holds or is doing, in a line, as My places lists it. */
export const KIT_OUTCOME: Record<KitStatus, string> = {
  building: "Being built: it opens as soon as it is ready",
  ready: "Ad copy, the window poster, tracked links and the report",
  failed: "Not built: open it to build it again",
};

/** Why a kit could not be made or built again, in plain words; a bare 429 says this address made too many. */
export function kitError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 429 && !error.explained) {
    return "Too many kits were started from this address just now. Try again in a little while.";
  }
  return plainError(error, fallback);
}

/** The launch plan's channel names, as kit.py's CHANNELS maps them to the copy it writes. */
const PLAN_CHANNELS: Record<string, ChannelKey> = {
  "Spotify Ads": "spotify",
  Nextdoor: "nextdoor",
  "Google Ads custom segment": "google_search",
  "Meta or Google local ads": "meta",
};

/** Each piece of copy, as the kit offer and the kit page name it. */
export const CHANNEL_NAMES: Record<ChannelKey, string> = {
  spotify: "a Spotify audio ad",
  nextdoor: "a Nextdoor post",
  google_search: "Google search ads",
  meta: "Meta ads",
  poster: "the window poster",
};

/** The copy a kit for this launch plan holds: one piece per channel of the plan, and always the poster. */
export function kitChannels(plan: LaunchPlan | null | undefined): ChannelKey[] {
  const present = new Set((plan?.channels ?? []).map((channel) => PLAN_CHANNELS[channel.channel]));
  return (["spotify", "nextdoor", "google_search", "meta", "poster"] as const).filter((key) => key === "poster" || present.has(key));
}

/** A QR code as one SVG path of unit squares, with its size in modules; medium error correction survives a scuffed print. */
export function qrPath(text: string): { size: number; path: string } {
  const code = qrcode(0, "M");
  code.addData(text);
  code.make();
  const size = code.getModuleCount();
  const parts: string[] = [];
  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      if (code.isDark(row, col)) parts.push(`M${col} ${row}h1v1h-1z`);
    }
  }
  return { size, path: parts.join("") };
}

/** "goldenhour.cafe/menu": a link as a poster prints it, without the scheme, the tags or a trailing slash. */
export function shortLink(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
    return `${parsed.host.replace(/^www\./, "")}${path}`;
  } catch {
    return url;
  }
}

/** The line over the poster's QR code: where it leads, as much of that as fits `width` once set. */
export function scanCaption(url: string, width: number, measure: (line: string) => number): string {
  const short = shortLink(url).toUpperCase();
  const host = short.split("/")[0] ?? short;
  const lines = [`SCAN · ${short}`, `SCAN · ${host}`, "SCAN WITH YOUR CAMERA"];
  return lines.find((line) => measure(line) <= width) ?? "SCAN";
}

/** What the owner typed as their link, as a link: "walkin.cafe" -> "https://walkin.cafe/"; null if it is not one. Any
 * http(s) address of a page of theirs will do: a website, an Instagram or Facebook page, a Google Maps listing or a
 * WhatsApp link. */
export function websiteUrl(text: string): string | null {
  const typed = text.trim();
  if (!typed || /\s/.test(typed)) return null;
  try {
    const url = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(typed) ? typed : `https://${typed}`);
    const host = url.hostname;
    if ((url.protocol !== "https:" && url.protocol !== "http:") || !(host.includes(".") || host === "localhost")) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** The kind of page an owner's link opens; the tracking tags only count where the owner can read them: a website. */
export type LinkKind = "website" | "instagram" | "facebook" | "maps" | "whatsapp";

/** Each kind of page as a sentence names it ("open your Instagram page"), and the service, which reads no tags. */
export const LINK_KINDS: Record<LinkKind, { page: string; service: string }> = {
  website: { page: "your website", service: "your website" },
  instagram: { page: "your Instagram page", service: "Instagram" },
  facebook: { page: "your Facebook page", service: "Facebook" },
  maps: { page: "your Google Maps listing", service: "Google Maps" },
  whatsapp: { page: "a WhatsApp chat with you", service: "WhatsApp" },
};

/** "https://www.instagram.com/goldenhour" -> "instagram"; a page on any other site is a website. */
export function linkKind(url: string): LinkKind {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "website";
  }
  const host = parsed.hostname.toLowerCase().replace(/^(www|m)\./, "");
  const on = (domain: string) => host === domain || host.endsWith(`.${domain}`);
  if (on("instagram.com") || host === "instagr.am") return "instagram";
  if (on("facebook.com") || host === "fb.com" || host === "fb.me") return "facebook";
  if (host === "wa.me" || on("whatsapp.com")) return "whatsapp";
  const googleMaps = /^google\.[a-z.]+$/.test(host) && parsed.pathname.startsWith("/maps");
  if (googleMaps || host === "maps.app.goo.gl" || host === "g.page" || /^maps\.google\.[a-z.]+$/.test(host)) return "maps";
  if (host === "goo.gl" && parsed.pathname.startsWith("/maps")) return "maps";
  return "website";
}

/** The landing page with a channel's UTM tags; tags already on the page give way to the channel's. */
export function trackedUrl(base: string, query: string): string {
  const url = new URL(base);
  for (const [key, value] of new URLSearchParams(query)) url.searchParams.set(key, value);
  return url.href;
}

/** A path the API returns ("/s/abc?sheet=0") as a link to share. */
export function absoluteUrl(path: string, origin = window.location.origin): string {
  return new URL(path, origin).href;
}

/** A text as a CSS string, for `content`: nothing in it can end the string or the rule it is set in. */
export function cssString(text: string): string {
  const flat = text.replace(/\p{Cc}+/gu, " ").trim();
  return `"${flat.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/**
 * The cover map's letter for each place of the report's travel list, "A", "B"…: the server letters a trip by its place
 * in the list, so a place without a location keeps its letter off the map and gets none here.
 */
export function travelLetters(places: { name: string }[], trips: { key: string; name: string }[]): (string | null)[] {
  const named = new Map(trips.map((trip) => [trip.key, trip.name]));
  return places.map((place, index) => {
    const key = String.fromCharCode(65 + index);
    return index < 26 && named.get(key) === place.name ? key : null;
  });
}

const RUNNING_FACE = '"Geist Mono Variable", "Geist Mono", ui-monospace, Menlo, Consolas, monospace';
const RUNNING_TYPE = `font-family: ${RUNNING_FACE}; font-size: 7pt; font-weight: 500; letter-spacing: 0.08em; color: #44443f;`;

/**
 * The report's paper, for a <style> element on its page: the business's name and "Walk-in report" run at the top of
 * every page after the cover, and what prepared it and the page count at the foot. Every value is fixed: Chromium
 * ignores CSS variables inside @page. The margins leave the same text block on A4 (210 × 297 mm) and US Letter
 * (215.9 × 279.4 mm): at most 174 mm wide and 241 mm tall.
 */
export function reportPageCss(name: string, foot: string): string {
  const top = `${RUNNING_TYPE} text-transform: uppercase; vertical-align: bottom; padding-bottom: 4mm;`;
  const bottom = `${RUNNING_TYPE} vertical-align: top; padding-top: 4mm;`;
  return [
    "@page report {",
    "  margin: 20mm 18mm 18mm 18mm;",
    `  @top-left { content: ${cssString(name)}; ${top} }`,
    `  @top-right { content: "Walk-in report"; ${top} }`,
    `  @bottom-left { content: ${cssString(foot)}; ${bottom} }`,
    `  @bottom-right { content: "Page " counter(page) " of " counter(pages); ${bottom} }`,
    "}",
    "@page report:first {",
    "  @top-left { content: none; }",
    "  @top-right { content: none; }",
    "}",
  ].join("\n");
}
