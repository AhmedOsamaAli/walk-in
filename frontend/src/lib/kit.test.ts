import { describe, expect, it } from "vitest";
import type { LatLon, LaunchPlan } from "../api/types";
import { fitWalk, kitChannels, qrPath, shortLink } from "./kit";

const RING: LatLon[] = [
  [30.26, -97.725],
  [30.265, -97.72],
  [30.26, -97.715],
  [30.255, -97.72],
  [30.26, -97.725],
];

function plan(channels: string[]): LaunchPlan {
  return {
    audience: { crowd: [], artists: [], podcasts: [], screen: [], brands: [], shared: [] },
    where: { minutes: 10, reach_m: 556, neighborhoods: [], sites_like: [] },
    when: { times: [], intents: [] },
    claims: [],
    channels: channels.map((channel) => ({ channel, setting: "x", why: "y" })),
    cautions: [],
  };
}

describe("the kit's channels", () => {
  it("writes one piece per channel of the plan, and always the poster", () => {
    const all = ["Meta or Google local ads", "Spotify Ads", "Nextdoor", "Google Ads custom segment"];
    expect(kitChannels(plan(all))).toEqual(["spotify", "nextdoor", "google_search", "meta", "poster"]);
    expect(kitChannels(plan(["Spotify Ads", "Meta or Google local ads", "Somewhere new"]))).toEqual(["spotify", "meta", "poster"]);
    expect(kitChannels(null)).toEqual(["poster"]);
  });
});

describe("the walk in a frame", () => {
  it("fits the outline inside the padding, north up, keeping its proportions", () => {
    const fitted = fitWalk(RING, [30.26, -97.72], 400, 300, 20);
    const points = [...fitted.path.matchAll(/(\d+(?:\.\d+)?) (\d+(?:\.\d+)?)/g)].map(
      (match): [number, number] => [Number(match[1]), Number(match[2])],
    );
    expect(fitted.path.startsWith("M") && fitted.path.endsWith("Z")).toBe(true);
    expect(points).toHaveLength(RING.length);
    for (const [x, y] of points) {
      expect(x).toBeGreaterThanOrEqual(19.9);
      expect(x).toBeLessThanOrEqual(380.1);
      expect(y).toBeGreaterThanOrEqual(19.9);
      expect(y).toBeLessThanOrEqual(280.1);
    }
    // The diamond is taller than it is wide once longitude is shrunk at 30°N, so the height sets the scale.
    const ys = points.map(([, y]) => y);
    expect(Math.min(...ys)).toBeCloseTo(20, 0);
    expect(Math.max(...ys)).toBeCloseTo(280, 0);
    // The northern point is at the top.
    expect(points[1]?.[1]).toBeCloseTo(20, 0);
    expect(fitted.site).toEqual([200, 150]);
    expect(fitted.metresPerUnit).toBeGreaterThan(3);
  });

  it("draws nothing for a walk without an outline, but still places the site", () => {
    const fitted = fitWalk([], [30.26, -97.72], 100, 100, 10);
    expect(fitted.path).toBe("");
    expect(fitted.site).toEqual([50, 50]);
  });
});

describe("poster lines", () => {
  it("prints a link without its scheme and tags", () => {
    expect(shortLink("https://www.goldenhour.cafe/?utm_source=poster")).toBe("goldenhour.cafe");
    expect(shortLink("https://goldenhour.cafe/menu/?utm_source=poster")).toBe("goldenhour.cafe/menu");
    expect(shortLink("not a url")).toBe("not a url");
  });
});

describe("the QR code", () => {
  it("encodes a link as a square of modules", () => {
    const { size, path } = qrPath("https://goldenhour.cafe/?utm_source=poster&utm_medium=qr&utm_campaign=golden-hour-launch");
    expect(size).toBeGreaterThanOrEqual(21);
    expect((size - 17) % 4).toBe(0);
    expect(path.startsWith("M0 0h1v1h-1z")).toBe(true);
    expect(qrPath("https://goldenhour.cafe/").path).not.toBe(path);
  });
});
