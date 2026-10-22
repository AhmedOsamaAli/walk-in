import type { Preset } from "../api/types";

/**
 * The sites the brief offers, as the server lists them (PRESETS in app/main.py): the brief shows these at once, even
 * while the survey engine naps, and /api/presets replaces them when it answers.
 */
export const PRESETS: readonly Preset[] = [
  {
    id: "ues",
    label: "Upper East Side, Manhattan",
    lat: 40.7736,
    lon: -73.9566,
    blurb: "Quiet residential blocks whose favorite spots are all downtown",
  },
  {
    id: "williamsburg",
    label: "Williamsburg, Brooklyn",
    lat: 40.7145,
    lon: -73.958,
    blurb: "Bars and brunch everywhere. What is still missing?",
  },
  { id: "les", label: "Lower East Side, Manhattan", lat: 40.7183, lon: -73.9884, blurb: "Dense, young and nocturnal" },
  {
    id: "east_austin",
    label: "East Austin, Texas",
    lat: 30.2622,
    lon: -97.7247,
    blurb: "A fast-changing neighborhood beyond New York",
  },
  {
    id: "zamalek",
    label: "Zamalek, Cairo",
    lat: 30.0626,
    lon: 31.2197,
    blurb: "Works beyond the US: Cairo's island district",
  },
];
