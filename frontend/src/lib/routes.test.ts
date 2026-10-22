import { describe, expect, it } from "vitest";
import { parseRoute, surveyUrl } from "./routes";

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

  it("shows the brief for every other address, including the pages still to come", () => {
    for (const path of ["/", "", "/s", "/s/", "/s/abc/extra", "/s/a%20b", "/s/a.b", "/k/kit-token", "/p/42", "/elsewhere"]) {
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
});
