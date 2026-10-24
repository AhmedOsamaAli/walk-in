import { describe, expect, it } from "vitest";
import { dossierUrl, isPage, kitUrl, pageUrl, parseRoute, PLACES_URL, PRIVACY_URL, samePage, surveyUrl } from "./routes";

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

  it("reads a launch kit and its report by the kit's token, whatever the query", () => {
    const token = "Zq3_x-9KpL0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV";
    expect(parseRoute(`/k/${token}`, "")).toEqual({ page: "kit", token });
    expect(parseRoute(`/k/${token}/`, "?utm_source=poster&utm_medium=qr")).toEqual({ page: "kit", token });
    expect(parseRoute(`/k/${token}/dossier`, "")).toEqual({ page: "dossier", token });
    expect(parseRoute(`/k/${token}/dossier/`, "?sheet=1")).toEqual({ page: "dossier", token });
    expect(parseRoute(`/k/${"a".repeat(64)}`, "")).toEqual({ page: "kit", token: "a".repeat(64) });
    expect(isPage({ page: "kit", token })).toBe(true);
    expect(isPage({ page: "dossier", token })).toBe(true);
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
      "/k/a%20b",
      "/k/tok_1/extra",
      "/k/tok_1/dossier/extra",
      "/k/tok_1/report",
      "/k//dossier",
      "/kits/tok_1",
      "/p/c4f1e2",
      "/elsewhere",
    ]) {
      expect(parseRoute(path, "?sheet=1")).toEqual({ page: "brief" });
    }
    expect(parseRoute(`/s/${"a".repeat(65)}`, "")).toEqual({ page: "brief" });
    expect(parseRoute(`/k/${"a".repeat(65)}`, "")).toEqual({ page: "brief" });
    expect(parseRoute(`/k/${"a".repeat(65)}/dossier`, "")).toEqual({ page: "brief" });
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

  it("builds a kit's and its report's addresses and reads them back", () => {
    expect(kitUrl("tok_1")).toBe("/k/tok_1");
    expect(dossierUrl("tok_1")).toBe("/k/tok_1/dossier");
    expect(pageUrl({ page: "kit", token: "tok_1" })).toBe("/k/tok_1");
    expect(pageUrl({ page: "dossier", token: "tok_1" })).toBe("/k/tok_1/dossier");
    for (const route of [
      { page: "kit", token: "tok_1" },
      { page: "dossier", token: "A-b_9" },
    ] as const) {
      const url = new URL(pageUrl(route), "https://walk-in.example");
      expect(parseRoute(url.pathname, url.search)).toEqual(route);
    }
  });

  it("tells one kit's pages from another's, so Back and Forward between them change the page", () => {
    expect(samePage({ page: "kit", token: "a" }, { page: "kit", token: "a" })).toBe(true);
    expect(samePage({ page: "kit", token: "a" }, { page: "kit", token: "b" })).toBe(false);
    expect(samePage({ page: "kit", token: "a" }, { page: "dossier", token: "a" })).toBe(false);
    expect(samePage({ page: "dossier", token: "a" }, { page: "dossier", token: "a" })).toBe(true);
    expect(samePage({ page: "kit", token: "a" }, { page: "places" })).toBe(false);
  });
});
