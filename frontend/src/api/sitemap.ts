/* The kit's maps as app/basemap.py and app/survey/{kit,dossier}.py give them: the street map around the walk, the report
   cover's pins and trips, and the poster's trips. The kit payload carries them as `dossier.cover.map` and `poster.map`;
   lib/sitemap.ts reads them from there. Street data © OpenStreetMap contributors (ODbL). */
import type { LatLon } from "./types";

export type StreetLayer = "primary" | "secondary" | "residential" | "pedestrian";

/** The streets, water and parks in a box around the walk, as [lat, lon] lines and rings cut to the box. */
export interface StreetMap {
  /** [[south, west], [north, east]]: where the street data stops. */
  box: [LatLon, LatLon];
  /** The street layers asked for: every one for a walk, the main roads only for a much larger area. */
  layers?: StreetLayer[];
  /** From the roads a city is read by to the streets only people on foot use; a layer not asked for may be absent. */
  streets: Partial<Record<StreetLayer, LatLon[][]>>;
  /** Rings, counterclockwise around water and clockwise around its islands: fill them with the nonzero rule. */
  water: LatLon[][];
  parks: LatLon[][];
  points: number;
  tolerance_m: number;
  /** Layers left out to keep the map small, least telling first. */
  dropped: string[];
  /** "© OpenStreetMap contributors", shown wherever the map is. */
  credit: string;
  /** The Overpass instance that answered, and when its data was last updated. */
  source?: string | null;
  as_of?: string | null;
}

/** A place of the concept's kind inside the area, in the report's competition table's order. */
export interface MapPin {
  /** The number the survey's map gives it (the first six it lists, with a location); null for a dot. */
  n: number | null;
  name: string;
  lat: number;
  lon: number;
  /** One that competes in earnest, rather than one that only sells it on the side. */
  main: boolean;
  distance_m: number;
}

/** A place people here love of the kind, outside the area: a trip they make now, lettered as the report lists it. */
export interface MapTrip {
  key: string;
  name: string;
  lat: number;
  lon: number;
  /** Straight-line kilometres from the site. */
  km: number;
  /** Degrees clockwise from north, from the site. */
  bearing: number;
}

/** The poster's trips: how far and which way, never which place. */
export interface PosterTrip {
  km: number;
  bearing: number;
}

/** The report cover's map: what the report recommends, in place. */
export interface CoverMap {
  streets: StreetMap | null;
  pins: MapPin[];
  trips: MapTrip[];
  /** The claim the map shows, in one line: "1 seafood place inside the 10-minute walk; people here travel…". */
  caption: string;
  basis: string;
}

/** The window poster's map. */
export interface PosterMap {
  streets: StreetMap | null;
  trips: PosterTrip[];
  /** "3.4 km: where people here go for seafood now"; null when the launch plan may not say people travel for it. */
  caption: string | null;
}
