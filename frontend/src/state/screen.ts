/* What the window shows (the brief, a survey's link while it loads, the survey in memory, or another page), the survey
   started here, and the design sheet open over a survey: the states the app's moves go between (App.tsx). */
import type { Area } from "../lib/area";
import { currentRoute, isPage, type PageRoute, type SurveyRoute } from "../lib/routes";
import type { Surveyed } from "../lib/titleBlock";
import type { Site } from "./site";

/** What the window shows: the brief, a survey's link while it loads, the survey in memory, or another page. */
export type Screen = { name: "brief" } | { name: "opening"; id: string } | { name: "survey" } | { name: "page"; route: PageRoute };

/** A survey started here, with the site and the area it surveys: the brief may move on to another site while it runs. */
export interface Started extends Surveyed {
  site: Site;
  area: Area;
}

/** The concept whose design sheet is open. */
export interface OpenSheet {
  runId: string;
  index: number;
  /** Where focus returns when the sheet closes; null for a sheet opened from a link. */
  opener: HTMLElement | null;
}

/** A survey's link starts on its loading screen; the other pages show themselves; every other address shows the brief. */
export function firstScreen(): Screen {
  const route = currentRoute();
  if (route.page === "survey") return { name: "opening", id: route.id };
  return isPage(route) ? { name: "page", route } : { name: "brief" };
}

/** The design sheet a survey's link names (`?sheet=`), opened from no poster. */
export const linkedSheet = (route: SurveyRoute): OpenSheet | null =>
  route.sheet === null ? null : { runId: route.id, index: route.sheet, opener: null };
