import { describe, expect, it } from "vitest";
import type { Concept } from "../api/types";
import { agesText, DOMAIN_LABELS, drawsText, genderWord, themeOf } from "./wildTheme";
import { PAIR_WILD, REALITY_TV, THEMED_WILD } from "./wildTheme.fixtures";

const withTheme = (theme: unknown): Concept => ({ ...THEMED_WILD, theme: theme as Concept["theme"] });

describe("themeOf", () => {
  it("reads a themed wild card's theme as the server sends it", () => {
    expect(themeOf(THEMED_WILD)).toEqual(REALITY_TV);
  });

  it("finds none on a wild card from before themes, or on a theme without a label", () => {
    expect(themeOf(PAIR_WILD)).toBeNull();
    expect(themeOf({ ...THEMED_WILD, theme: null })).toBeNull();
    expect(themeOf(withTheme({ ...REALITY_TV, label: "  " }))).toBeNull();
    expect(themeOf(withTheme("reality TV"))).toBeNull();
  });

  it("keeps only the titles it can show, and the program's lines", () => {
    const theme = themeOf(
      withTheme({
        label: " reality TV ",
        program: "Watch parties for Cheer",
        built_on: [{ domain: "games", id: "1", name: "Fortnite" }, { domain: "tv", id: "2", name: " " }, null, REALITY_TV.built_on[0]],
        draws: "female",
      }),
    );
    expect(theme).toEqual({
      key: "",
      label: "reality TV",
      program: ["Watch parties for Cheer"],
      built_on: [REALITY_TV.built_on[0]],
      draws: null,
      basis: "",
    });
    expect(themeOf(withTheme({ label: "reality TV", built_on: "Cheer" }))?.built_on).toEqual([]);
  });

  it("keeps who the titles draw only when Qloo showed a lean", () => {
    const draws = (value: unknown) => themeOf(withTheme({ ...REALITY_TV, draws: value }))?.draws;
    expect(draws({ ages: [], gender: null, basis: "Leans, not head counts." })).toBeNull();
    expect(draws({ ages: ["30–34"], gender: "nonsense" })).toEqual({ ages: ["30–34"], gender: null, basis: "" });
    expect(draws({ gender: "women" })).toEqual({ ages: [], gender: "female", basis: "" });
  });
});

describe("agesText", () => {
  it("makes one span of bands that run on", () => {
    expect(agesText(["25–29", "30–34"])).toBe("25–34");
    expect(agesText(["30–34", "35–44", "25–29"])).toBe("25–44");
    expect(agesText(["Under 25", "25–29"])).toBe("Under 30");
    expect(agesText(["45–54", "55+"])).toBe("45+");
    expect(agesText(["35–44"])).toBe("35–44");
  });

  it("keeps bands apart where an age group between them is left out", () => {
    expect(agesText(["Under 25", "35–44", "45–54"])).toBe("Under 25 and 35–54");
  });

  it("says names that are not Qloo's bands as they come, once each", () => {
    expect(agesText(["Gen Z", "Millennials", "Gen Z"])).toBe("Gen Z and Millennials");
  });
});

describe("who the titles draw", () => {
  it("names the gender however the server words it", () => {
    expect(["female", "Women", "male", "men", "nonbinary", null].map(genderWord)).toEqual([
      "female",
      "female",
      "male",
      "male",
      null,
      null,
    ]);
  });

  it("says it like the audience section: the ages first, then the gender", () => {
    expect(drawsText({ ages: ["25–29", "30–34"], gender: "female", basis: "" })).toBe(
      "Ages 25–34 most · leans toward women",
    );
    expect(drawsText({ ages: ["55+"], gender: null, basis: "" })).toBe("Ages 55+ most");
    expect(drawsText({ ages: ["Under 25"], gender: "men", basis: "" })).toBe("Ages under 25 most · leans toward men");
    expect(drawsText({ ages: [], gender: "male", basis: "" })).toBe("Leans toward men");
    expect(drawsText({ ages: [], gender: null, basis: "" })).toBeNull();
  });
});

it("labels each kind of title as a reader knows it", () => {
  expect(DOMAIN_LABELS).toEqual({ tv: "TV", movies: "Film", podcasts: "Podcast", artists: "Artist", brands: "Brand" });
});
