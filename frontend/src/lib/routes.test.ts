import { describe, expect, it } from "vitest";
import {
  dossierUrl,
  isPage,
  isPaymentRoute,
  kitUrl,
  pageUrl,
  parseRoute,
  pledgeUrl,
  PLACES_URL,
  PRIVACY_URL,
  samePage,
  surveyUrl,
  type PageRoute,
} from "./routes";

describe("routes", () => {
  it("reads a survey's id and its open design sheet", () => {
    expect(parseRoute("/s/3f9a0c1b2d4e", "")).toEqual({ page: "survey", id: "3f9a0c1b2d4e", sheet: null });
    expect(parseRoute("/s/3f9a0c1b2d4e/", "")).toEqual({ page: "survey", id: "3f9a0c1b2d4e", sheet: null });
    expect(parseRoute("/s/3f9a0c1b2d4e", "?sheet=1")).toEqual({ page: "survey", id: "3f9a0c1b2d4e", sheet: 1 });
    expect(parseRoute("/s/run_2-b", "?utm=x&sheet=0")).toEqual({ page: "survey", id: "run_2-b", sheet: 0 });
  });

  it("ignores a sheet that is not a concept's index", () => {
    for (const search of ["?sheet=", "?sheet=-1", "?sheet=1.5", "?sheet=one", "?sheet=999", "?sheets=1"]) {
      expect(parseRoute("/s/abc", search)).toEqual({ page: "survey", id: "abc", sheet: null });
    }
  });

  it("reads My places and the privacy note", () => {
    expect(parseRoute("/me", "")).toEqual({ page: "places" });
    expect(parseRoute("/me/", "?utm_source=x")).toEqual({ page: "places" });
    expect(parseRoute("/privacy", "")).toEqual({ page: "privacy" });
    expect(parseRoute("/privacy/", "?from=footer")).toEqual({ page: "privacy" });
    expect(isPage({ page: "places" })).toBe(true);
    expect(isPage({ page: "privacy" })).toBe(true);
    expect(isPage({ page: "brief" })).toBe(false);
    expect(isPage({ page: "survey", id: "r1", sheet: null })).toBe(false);
  });

  it("shows the brief for every other address", () => {
    for (const path of [
      "/",
      "",
      "/s",
      "/s/",
      "/s/abc/extra",
      "/s/a%20b",
      "/s/a.b",
      "/me/x",
      "/mine",
      "/privacy/x",
      "/privacy-policy",
      "/k",
      "/k/",
      "/k/a.b",
      "/k/abc/print",
      "/k/abc/dossier/x",
      "/p",
      "/p/",
      "/p/a/b",
      "/elsewhere",
    ]) {
      expect(parseRoute(path, "?sheet=1")).toEqual({ page: "brief" });
    }
    expect(parseRoute(`/s/${"a".repeat(65)}`, "")).toEqual({ page: "brief" });
  });

  it("builds a survey's address, with the open sheet, and reads it back", () => {
    expect(surveyUrl("3f9a0c1b2d4e")).toBe("/s/3f9a0c1b2d4e");
    expect(surveyUrl("3f9a0c1b2d4e", 2)).toBe("/s/3f9a0c1b2d4e?sheet=2");
    expect(surveyUrl("3f9a0c1b2d4e", null)).toBe("/s/3f9a0c1b2d4e");
    for (const sheet of [null, 0, 2]) {
      const url = new URL(surveyUrl("3f9a0c1b2d4e", sheet), "https://walk-in.example");
      expect(parseRoute(url.pathname, url.search)).toEqual({ page: "survey", id: "3f9a0c1b2d4e", sheet });
    }
  });

  it("builds My places' and the privacy note's addresses and reads them back", () => {
    expect(pageUrl({ page: "places" })).toBe(PLACES_URL);
    expect(pageUrl({ page: "privacy" })).toBe(PRIVACY_URL);
    for (const route of [{ page: "places" }, { page: "privacy" }] as const) {
      expect(parseRoute(pageUrl(route), "")).toEqual(route);
    }
    expect(samePage({ page: "places" }, { page: "places" })).toBe(true);
    expect(samePage({ page: "privacy" }, { page: "privacy" })).toBe(true);
    expect(samePage({ page: "places" }, { page: "privacy" })).toBe(false);
  });
});

// Payments only: these leave with the payment UI.
describe("payment routes", () => {
  it("reads the kit, dossier and pledge pages", () => {
    const token = "Zk3_q9-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789";
    expect(parseRoute(`/k/${token}`, "")).toEqual({ page: "kit", token });
    expect(parseRoute(`/k/${token}/`, "?utm_source=poster")).toEqual({ page: "kit", token });
    expect(parseRoute(`/k/${token}/dossier`, "")).toEqual({ page: "dossier", token });
    expect(parseRoute(`/k/${token}/dossier/`, "")).toEqual({ page: "dossier", token });
    expect(parseRoute("/p/c4f1e2", "")).toEqual({ page: "pledge", id: "c4f1e2", withdraw: null });
    expect(parseRoute("/p/c4f1e2", "?utm_source=poster&utm_medium=qr")).toEqual({ page: "pledge", id: "c4f1e2", withdraw: null });
    expect(parseRoute("/p/c4f1e2", "?withdraw=w_T0k-en")).toEqual({ page: "pledge", id: "c4f1e2", withdraw: "w_T0k-en" });
    expect(parseRoute(`/p/${"a".repeat(65)}`, "")).toEqual({ page: "brief" });
    expect(parseRoute(`/k/${"a".repeat(129)}`, "")).toEqual({ page: "brief" });
  });

  it("drops a withdraw token that is not one", () => {
    for (const search of ["?withdraw=", "?withdraw=a%20b", "?withdraw=a.b", `?withdraw=${"w".repeat(129)}`]) {
      expect(parseRoute("/p/c4f1e2", search)).toEqual({ page: "pledge", id: "c4f1e2", withdraw: null });
    }
  });

  it("builds every payment page's address and reads it back", () => {
    const pages: PageRoute[] = [
      { page: "kit", token: "tok_1" },
      { page: "dossier", token: "tok_1" },
      { page: "pledge", id: "c1", withdraw: null },
      { page: "pledge", id: "c1", withdraw: "w-1" },
    ];
    for (const route of pages) {
      const url = new URL(pageUrl(route), "https://walk-in.example");
      const read = parseRoute(url.pathname, url.search);
      expect(read).toEqual(route);
      expect(isPage(read) && isPaymentRoute(read)).toBe(true);
    }
    expect(kitUrl("tok_1")).toBe("/k/tok_1");
    expect(dossierUrl("tok_1")).toBe("/k/tok_1/dossier");
    expect(pledgeUrl("c1", "w-1")).toBe("/p/c1?withdraw=w-1");
    expect(isPaymentRoute({ page: "places" })).toBe(false);
  });

  it("tells a payment page from another, whatever its query", () => {
    expect(samePage({ page: "pledge", id: "c1", withdraw: "w" }, { page: "pledge", id: "c1", withdraw: null })).toBe(true);
    expect(samePage({ page: "pledge", id: "c1", withdraw: null }, { page: "pledge", id: "c2", withdraw: null })).toBe(false);
    expect(samePage({ page: "kit", token: "a" }, { page: "kit", token: "a" })).toBe(true);
    expect(samePage({ page: "kit", token: "a" }, { page: "dossier", token: "a" })).toBe(false);
    expect(samePage({ page: "kit", token: "a" }, { page: "kit", token: "b" })).toBe(false);
    expect(samePage({ page: "places" }, { page: "kit", token: "a" })).toBe(false);
  });
});
