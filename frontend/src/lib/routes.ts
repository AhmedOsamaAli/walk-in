/** What a URL asks for: a survey by its run id, with one concept's design sheet open, or the brief. */
export type Route = { page: "brief" } | SurveyRoute;

export interface SurveyRoute {
  page: "survey";
  id: string;
  /** The concept whose design sheet is open, from `?sheet=`. */
  sheet: number | null;
}

export const BRIEF_URL = "/";

const SURVEY_PATH = /^\/s\/([A-Za-z0-9_-]{1,64})\/?$/;
const SHEET = /^\d{1,2}$/;

/** "/s/{id}" is a survey; "/", the /k/ and /p/ pages still to come and any other path show the brief. */
export function parseRoute(pathname: string, search: string): Route {
  const id = SURVEY_PATH.exec(pathname)?.[1];
  if (!id) return { page: "brief" };
  const sheet = new URLSearchParams(search).get("sheet");
  return { page: "survey", id, sheet: sheet !== null && SHEET.test(sheet) ? Number(sheet) : null };
}

/** "/s/{id}", with "?sheet={index}" while a concept's design sheet is open. */
export function surveyUrl(id: string, sheet: number | null = null): string {
  const path = `/s/${encodeURIComponent(id)}`;
  return sheet === null ? path : `${path}?sheet=${sheet}`;
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
