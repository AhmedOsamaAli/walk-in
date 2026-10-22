/* The launch kit's drawing and wording helpers: the channels it writes for, the walk drawn to fit a frame, poster
   lines and the QR code. Pure functions, so they are tested without a browser. */
import qrcode from "qrcode-generator";
import type { ChannelKey } from "../api/kit";
import type { LatLon, LaunchPlan } from "../api/types";

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

export interface Fitted {
  /** The walk as an SVG path in the frame's coordinates, closed. */
  path: string;
  /** The site's point in the frame. */
  site: [number, number];
  /** Metres per frame unit, for a scale bar. */
  metresPerUnit: number;
}

const METRES_PER_DEGREE = 111_320;

/**
 * The walk's outline ([lat, lon] points) and the site, drawn to fit a frame of `width` by `height` with `pad` around:
 * an equirectangular projection at the site's latitude, north up, keeping the walk's true proportions.
 */
export function fitWalk(ring: LatLon[], site: LatLon, width: number, height: number, pad: number): Fitted {
  const [lat0, lon0] = site;
  const shrink = Math.cos((lat0 * Math.PI) / 180);
  const points = [...ring, site].map(([lat, lon]) => [(lon - lon0) * shrink, lat - lat0] as const);
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanY = Math.max(maxY - minY, 1e-6);
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const [middleX, middleY] = [(minX + maxX) / 2, (minY + maxY) / 2];
  const at = (x: number, y: number): [number, number] => [
    round(width / 2 + (x - middleX) * scale),
    round(height / 2 - (y - middleY) * scale),
  ];
  const drawn = ring.map(([lat, lon]) => at((lon - lon0) * shrink, lat - lat0));
  const path = drawn.length ? `M${drawn.map(([x, y]) => `${x} ${y}`).join("L")}Z` : "";
  return { path, site: at(0, 0), metresPerUnit: METRES_PER_DEGREE / scale };
}

const round = (value: number) => Math.round(value * 10) / 10;

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
