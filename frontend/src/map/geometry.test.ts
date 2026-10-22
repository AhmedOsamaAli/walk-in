import { describe, expect, it } from "vitest";
import { distanceM } from "./geometry";

describe("distanceM", () => {
  it("measures great-circle distances", () => {
    expect(distanceM([30.0626, 31.2197], [30.0626, 31.2197])).toBe(0);
    // Zamalek to the East Austin pin: the arc the map once drew across the Atlantic.
    expect(Math.round(distanceM([30.0626, 31.2197], [30.2622, -97.7247]) / 1000)).toBe(11_404);
    // One degree of latitude is about 111 km.
    expect(Math.round(distanceM([40, -74], [41, -74]) / 1000)).toBe(111);
  });
});
