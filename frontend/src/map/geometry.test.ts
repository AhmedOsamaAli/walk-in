import { describe, expect, it } from "vitest";
import { circleWalk, distanceM, isBigArea, reachM } from "./geometry";

describe("the circle drawn when an area cannot be traced", () => {
  it("reaches as far as the server's: 80 m a minute walking, 400 m a minute driving, 700 m a km of road", () => {
    expect(reachM({ travel: "walk", minutes: 10 })).toBe(800);
    expect(reachM({ travel: "drive", minutes: 30 })).toBe(12_000);
    expect(reachM({ travel: "distance", km: 25 })).toBe(17_500);
  });

  it("names itself as the traced area would, and takes a bare number of minutes as a walk", () => {
    const drive = circleWalk(30.0626, 31.2197, { travel: "drive", minutes: 30 });
    expect(drive).toMatchObject({ source: "circle", travel: "drive", minutes: 30, radius_m: 12_000, short: "30-min drive" });
    expect(drive.label).toBe("30-minute drive");
    const road = circleWalk(30.0626, 31.2197, { travel: "distance", km: 25 });
    expect(road).toMatchObject({ travel: "distance", km: 25, radius_m: 17_500, short: "25 km drive" });
    expect(circleWalk(30.0626, 31.2197, 5)).toMatchObject({ travel: "walk", minutes: 5, area_km2: 0.503, short: "5-min walk" });
    expect(drive.ring).toHaveLength(41);
  });

  it("calls an area big once it reaches past a 15-minute walk", () => {
    expect(isBigArea({ travel: "walk", minutes: 15 })).toBe(false);
    expect(isBigArea({ travel: "walk", minutes: 30 })).toBe(true);
    expect(isBigArea({ travel: "drive", minutes: 5 })).toBe(true);
    expect(isBigArea({ travel: "distance", km: 1 })).toBe(false);
    expect(isBigArea({ travel: "distance", km: 5 })).toBe(true);
  });
});

describe("distanceM", () => {
  it("measures great-circle distances", () => {
    expect(distanceM([30.0626, 31.2197], [30.0626, 31.2197])).toBe(0);
    // Zamalek to the East Austin pin: the arc the map once drew across the Atlantic.
    expect(Math.round(distanceM([30.0626, 31.2197], [30.2622, -97.7247]) / 1000)).toBe(11_404);
    // One degree of latitude is about 111 km.
    expect(Math.round(distanceM([40, -74], [41, -74]) / 1000)).toBe(111);
  });
});
