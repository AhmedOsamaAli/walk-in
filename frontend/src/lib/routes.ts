/**
 * What a URL asks for: the brief, a survey by its run id (with one concept's design sheet open), the signed-in user's
 * places, the privacy note, or one of the payment pages.
 */
export type Route = { page: "brief" } | SurveyRoute | PageRoute;

export interface SurveyRoute {
  page: "survey";
  id: string;
  /** The concept whose design sheet is open, from `?sheet=`. */
  sheet: number | null;
}

/** The pages that are not the survey sheet and its map. */
export type PageRoute = { page: "places" } | { page: "privacy" } | PaymentRoute;

export const BRIEF_URL = "/";
export const PLACES_URL = "/me";
export const PRIVACY_URL = "/privacy";

const SURVEY_PATH = /^\/s\/([A-Za-z0-9_-]{1,64})\/?$/;
const PLACES_PATH = /^\/me\/?$/;
const PRIVACY_PATH = /^\/privacy\/?$/;
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
  return paymentRoute(pathname, params) ?? { page: "brief" };
}

export function isPage(route: Route): route is PageRoute {
  return route.page !== "brief" && route.page !== "survey";
}

/** "/s/{id}", with "?sheet={index}" while a concept's design sheet is open. */
export function surveyUrl(id: string, sheet: number | null = null): string {
  const path = `/s/${encodeURIComponent(id)}`;
  return sheet === null ? path : `${path}?sheet=${sheet}`;
}

/** The address a page route shows. */
export function pageUrl(route: PageRoute): string {
  if (route.page === "places") return PLACES_URL;
  if (route.page === "privacy") return PRIVACY_URL;
  return paymentUrl(route);
}

/** Whether two page routes show the same page, whatever their query: a withdraw link and its campaign are one page. */
export function samePage(a: PageRoute, b: PageRoute): boolean {
  if (a.page !== b.page) return false;
  return !isPaymentRoute(a) || !isPaymentRoute(b) || samePaymentPage(a, b);
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

// ---------- Payment pages: a launch kit and its dossier, and a pledge campaign. They leave with the payment UI. ----------

export type PaymentRoute =
  | { page: "kit"; token: string }
  | { page: "dossier"; token: string }
  | {
      page: "pledge";
      id: string;
      /** A supporter's withdraw token, from `?withdraw=`: the page asks to confirm the withdrawal. */
      withdraw: string | null;
    };

const KIT_PATH = /^\/k\/([A-Za-z0-9_-]{1,128})(\/dossier)?\/?$/;
const PLEDGE_PATH = /^\/p\/([A-Za-z0-9_-]{1,64})\/?$/;
const TOKEN = /^[A-Za-z0-9_-]{1,128}$/;

function paymentRoute(pathname: string, params: URLSearchParams): PaymentRoute | null {
  const kit = KIT_PATH.exec(pathname);
  if (kit?.[1]) return { page: kit[2] ? "dossier" : "kit", token: kit[1] };
  const pledge = PLEDGE_PATH.exec(pathname)?.[1];
  if (!pledge) return null;
  const withdraw = params.get("withdraw");
  return { page: "pledge", id: pledge, withdraw: withdraw !== null && TOKEN.test(withdraw) ? withdraw : null };
}

export function isPaymentRoute(route: Route): route is PaymentRoute {
  return route.page === "kit" || route.page === "dossier" || route.page === "pledge";
}

export const kitUrl = (token: string) => `/k/${encodeURIComponent(token)}`;
export const dossierUrl = (token: string) => `${kitUrl(token)}/dossier`;

/** "/p/{id}", with "?withdraw={token}" for a supporter's withdraw link. */
export function pledgeUrl(id: string, withdraw: string | null = null): string {
  const path = `/p/${encodeURIComponent(id)}`;
  return withdraw === null ? path : `${path}?${new URLSearchParams({ withdraw }).toString()}`;
}

function paymentUrl(route: PaymentRoute): string {
  if (route.page === "pledge") return pledgeUrl(route.id, route.withdraw);
  return route.page === "kit" ? kitUrl(route.token) : dossierUrl(route.token);
}

function samePaymentPage(a: PaymentRoute, b: PaymentRoute): boolean {
  if (a.page === "pledge") return b.page === "pledge" && a.id === b.id;
  return b.page !== "pledge" && a.page === b.page && a.token === b.token;
}
