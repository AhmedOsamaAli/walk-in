import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { DRIVE_WALK } from "../state/fixtures";
import { failedWalk, isAbort, NO_WALK, TRACE_DELAY_MS, TRACING_WALK, walkLine } from "./walk";

const ZAMALEK = { lat: 30.0626, lon: 31.2197 };

describe("the walk preview", () => {
  it("waits for the site to stay put for at least 600 ms before tracing", () => {
    expect(TRACE_DELAY_MS).toBeGreaterThanOrEqual(600);
  });

  it("rests after a 429, keeping the site and drawing nothing", () => {
    const preview = failedWalk(new ApiError("Too many map requests. Try again later.", 429, true), ZAMALEK, 10);
    expect(preview).toEqual({ phase: "resting" });
    expect(walkLine(preview, 10)).toMatch(/^The walk preview is resting.*Your site stays/);
  });

  it("draws the estimated circle after any other failure", () => {
    const preview = failedWalk(new ApiError("Request failed (502).", 502), ZAMALEK, 5);
    expect(preview.phase === "shown" ? preview.walk.source : null).toBe("circle");
    expect(walkLine(preview, 5)).toBe("5-min walk · 0.503 km² · estimated circle");
    expect(failedWalk(new TypeError("Failed to fetch"), ZAMALEK, 10).phase).toBe("shown");
  });

  it("says what it is doing, and why it takes long while the engine wakes", () => {
    expect(walkLine(NO_WALK, 10)).toBe("");
    expect(walkLine(TRACING_WALK, 10)).toBe("Tracing a 10-min walk…");
    expect(walkLine(TRACING_WALK, 15, true)).toMatch(/^Tracing the 15-min walk\. The survey engine is waking up/);
    const walk = { minutes: 10, source: "street network", ring: [], area_km2: 1.21, radius_m: 640 };
    expect(walkLine({ phase: "shown", walk }, 10)).toBe("10-min walk · 1.21 km² · street network");
  });

  it("names a drive or a road distance, in the server's words once traced", () => {
    const drive = { travel: "drive", minutes: 30 } as const;
    expect(walkLine(TRACING_WALK, drive)).toBe("Tracing a 30-min drive…");
    expect(walkLine(TRACING_WALK, { travel: "distance", km: 25 }, true)).toMatch(/^Tracing the 25 km drive\. The survey/);
    expect(walkLine({ phase: "shown", walk: DRIVE_WALK }, drive)).toBe("30-min drive · 210 km² · street network");
    expect(walkLine({ phase: "resting" }, drive)).toBe(
      "The drive preview is resting after many map requests. Your site stays, and the survey still traces the drive.",
    );
  });

  it("draws the circle of a drive or a road distance when it cannot be traced", () => {
    const drive = failedWalk(new ApiError("Request failed (502).", 502), ZAMALEK, { travel: "drive", minutes: 30 });
    expect(drive.phase === "shown" ? drive.walk.radius_m : null).toBe(12_000);
    expect(walkLine(drive, { travel: "drive", minutes: 30 })).toBe("30-min drive · 452 km² · estimated circle");
    const road = failedWalk(new TypeError("Failed to fetch"), ZAMALEK, { travel: "distance", km: 25 });
    expect(walkLine(road, { travel: "distance", km: 25 })).toBe("25 km drive · 962 km² · estimated circle");
  });

  it("knows an abandoned request from a failed one", () => {
    expect(isAbort(new DOMException("The request was aborted.", "AbortError"))).toBe(true);
    expect(isAbort(new Error("Request failed (500)."))).toBe(false);
  });
});
