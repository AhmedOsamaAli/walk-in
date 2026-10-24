/**
 * What a URL asks for: the brief, a survey by its run id (with one concept's design sheet open), the signed-in user's
 * places, the privacy note, the finished examples, or a launch kit by its token and the kit's report.
 */
export type Route = { page: "brief" } | SurveyRoute | PageRoute;

export interface SurveyRoute {
  page: "survey";
  id: string;
  /** The concept whose design sheet is open, from `?sheet=`. */
  sheet: number | null;
}

/** A launch kit (/k/{token}) or its report (/k/{token}/dossier): open to anyone with the link. */
export interface KitRoute {
  page: "kit" | "dossier";
  token: string;
}

/** The pages that are not the survey sheet and its map. */
export type PageRoute = { page: "places" } | { page: "privacy" } | { page: "examples" } | KitRoute;

export const BRIEF_URL = "/";
export const PLACES_URL = "/me";
export const PRIVACY_URL = "/privacy";
/** Finished surveys anyone can open before running one (features/EXAMPLES.md). */
export const EXAMPLES_URL = "/examples";

const SURVEY_PATH = /^\/s\/([A-Za-z0-9_-]{1,64})\/?$/;
const PLACES_PATH = /^\/me\/?$/;
const PRIVACY_PATH = /^\/privacy\/?$/;
const EXAMPLES_PATH = /^\/examples\/?$/;
// A kit's token, as the server checks it (app/routes/kits.py).
const KIT_PATH = /^\/k\/([A-Za-z0-9_-]{1,64})\/?$/;
const DOSSIER_PATH = /^\/k\/([A-Za-z0-9_-]{1,64})\/dossier\/?$/;
const SHEET = /^\d{1,2}$/;

/** Every path but these shows the brief. */
export function parseRoute(pathname: string, search: string): Route {
  const params = new URLSearchParams(search);
  const survey = SURVEY_PATH.exec(pathname)?.[1];
  if (survey) {
    const sheet = params.get("sheet");
    return { page: "survey", id: survey, sheet: sheet !== null && SHEET.test(sheet) ? Number(sheet) : null };
  }
  if (PLACES_PATH.test(pathname)) return { page: "places" };
  if (PRIVACY_PATH.test(pathname)) return { page: "privacy" };
  if (EXAMPLES_PATH.test(pathname)) return { page: "examples" };
  const kit = KIT_PATH.exec(pathname)?.[1];
  if (kit) return { page: "kit", token: kit };
  const dossier = DOSSIER_PATH.exec(pathname)?.[1];
  if (dossier) return { page: "dossier", token: dossier };
  return { page: "brief" };
}

export function isPage(route: Route): route is PageRoute {
  return route.page !== "brief" && route.page !== "survey";
}

/** "/s/{id}", with "?sheet={index}" while a concept's design sheet is open. */
export function surveyUrl(id: string, sheet: number | null = null): string {
  const path = `/s/${encodeURIComponent(id)}`;
  return sheet === null ? path : `${path}?sheet=${sheet}`;
}

/** "/k/{token}": a launch kit. */
export function kitUrl(token: string): string {
  return `/k/${encodeURIComponent(token)}`;
}

/** "/k/{token}/dossier": the kit's report, as a document to print or save as a PDF. */
export function dossierUrl(token: string): string {
  return `${kitUrl(token)}/dossier`;
}

/** The address a page route shows. */
export function pageUrl(route: PageRoute): string {
  switch (route.page) {
    case "places":
      return PLACES_URL;
    case "privacy":
      return PRIVACY_URL;
    case "examples":
      return EXAMPLES_URL;
    case "kit":
      return kitUrl(route.token);
    case "dossier":
      return dossierUrl(route.token);
  }
}

/** Whether two page routes show the same page, whatever their query: one kit's page is not another's. */
export function samePage(a: PageRoute, b: PageRoute): boolean {
  return pageUrl(a) === pageUrl(b);
}

export function currentRoute(): Route {
  return parseRoute(window.location.pathname, window.location.search);
}

/** The address without its hash: a section link changes only the hash, which is not a navigation. */
export function currentAddress(): string {
  return `${window.location.pathname}${window.location.search}`;
}

/** The address bar already shows the brief, with nothing after the slash. */
export function onBriefUrl(): boolean {
  return window.location.pathname === BRIEF_URL && !window.location.search && !window.location.hash;
}
