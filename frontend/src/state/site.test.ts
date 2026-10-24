import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { ReverseResult } from "../api/types";
import { DROPPED_PIN } from "../lib/fullmap";
import { addressAt, awaitsAddress, samePoint, withAddress, type Site } from "./site";

const PIN: Site = { id: null, label: DROPPED_PIN, lat: 40.71283, lon: -73.96112 };
const ADDRESS = "131 South 2nd Street, Williamsburg, Brooklyn";
const FOUND: ReverseResult = { label: ADDRESS, address: "131, South 2nd Street, Williamsburg, Brooklyn, New York, 11249, United States" };

describe("a dropped pin's address", () => {
  it("is looked up for a pin placed by hand, and for no site with a name", () => {
    expect(awaitsAddress(PIN)).toBe(true);
    expect(awaitsAddress({ ...PIN, label: "N 40.7128 · W 73.9611" })).toBe(true);
    expect(awaitsAddress({ ...PIN, label: ADDRESS })).toBe(false);
    expect(awaitsAddress({ id: "zamalek", label: "Zamalek, Cairo", lat: 30.0626, lon: 31.2197 })).toBe(false);
    expect(awaitsAddress(null)).toBe(false);
  });

  it("replaces the pin's label once it comes, while the pin has not moved", () => {
    expect(withAddress(PIN, { lat: PIN.lat, lon: PIN.lon }, ADDRESS)).toEqual({ ...PIN, label: ADDRESS });
  });

  it("is dropped when the pin has moved, been replaced or been named since", () => {
    const moved = { ...PIN, lat: 40.7131 };
    expect(withAddress(moved, PIN, ADDRESS)).toBe(moved);
    const searched: Site = { id: null, label: "Bedford Avenue, Williamsburg", lat: PIN.lat, lon: PIN.lon };
    expect(withAddress(searched, PIN, ADDRESS)).toBe(searched);
    const preset: Site = { id: "w", label: "Williamsburg, Brooklyn", lat: PIN.lat, lon: PIN.lon };
    expect(withAddress(preset, PIN, ADDRESS)).toBe(preset);
    expect(withAddress(null, PIN, ADDRESS)).toBeNull();
  });

  it("is the server's short label, asked for the pin's spot", async () => {
    const asked: [number, number][] = [];
    const reverse = (lat: number, lon: number) => {
      asked.push([lat, lon]);
      return Promise.resolve(FOUND);
    };
    await expect(addressAt(PIN, new AbortController().signal, reverse)).resolves.toBe(ADDRESS);
    expect(asked).toEqual([[PIN.lat, PIN.lon]]);
    const padded = () => Promise.resolve({ ...FOUND, label: `  ${ADDRESS} ` });
    await expect(addressAt(PIN, new AbortController().signal, padded)).resolves.toBe(ADDRESS);
  });

  it("is none when the point has no address, the lookup fails or the pin moved on", async () => {
    const signal = new AbortController().signal;
    const none = () => Promise.reject(new ApiError("No address at this point.", 404, true));
    await expect(addressAt(PIN, signal, none)).resolves.toBeNull();
    const down = () => Promise.reject(new ApiError("Address lookup is unavailable right now.", 502, true));
    await expect(addressAt(PIN, signal, down)).resolves.toBeNull();
    const offline = () => Promise.reject(new TypeError("Failed to fetch"));
    await expect(addressAt(PIN, signal, offline)).resolves.toBeNull();
    const blank = () => Promise.resolve({ label: " ", address: "" });
    await expect(addressAt(PIN, signal, blank)).resolves.toBeNull();
    const odd = () => Promise.resolve({ address: "x" } as unknown as ReverseResult);
    await expect(addressAt(PIN, signal, odd)).resolves.toBeNull();
    // The pin moved while the answer was on its way: the lookup was called off, and its answer is not used.
    const abort = new AbortController();
    const late = () => {
      abort.abort();
      return Promise.resolve(FOUND);
    };
    await expect(addressAt(PIN, abort.signal, late)).resolves.toBeNull();
  });

  it("compares spots, not names", () => {
    expect(samePoint(PIN, { lat: PIN.lat, lon: PIN.lon })).toBe(true);
    expect(samePoint(PIN, { ...PIN, lon: -73.9612 })).toBe(false);
    expect(samePoint(PIN, null)).toBe(false);
    expect(samePoint(undefined, PIN)).toBe(false);
  });
});
