import { describe, expect, it } from "vitest";
import { adSetting, adText, audienceTitle, bandsText, barSpan, chainLine, compareRows, leanWord, namedBands, namesOnce, peopleNote } from "./audience";
import { AUDIENCE_CLEAR, AUDIENCE_EVEN, AUDIENCE_GENERAL, AUDIENCE_INSIDE, AUDIENCE_LIVE, AUDIENCE_TIP, CHAIN, CHAIN_CAPPED } from "./audience.fixtures";

describe("who the loved places draw", () => {
  it("says the ad setting it implies, and nothing when there is no clear lean", () => {
    expect(adSetting(AUDIENCE_CLEAR)).toBe("ages 35–44, women");
    expect(adSetting({ ...AUDIENCE_CLEAR, gender: null })).toBe("ages 35–44, women and men");
    expect(adSetting({ ...AUDIENCE_CLEAR, age_min: 55, age_max: null, gender: "men" })).toBe("ages 55+, men");
    expect(adSetting({ ...AUDIENCE_CLEAR, age_min: null, age_max: 24 })).toBe("ages 24 and under, women");
    expect(adSetting({ ...AUDIENCE_EVEN, gender: "men" })).toBe("all ages, men");
    expect(adSetting(AUDIENCE_EVEN)).toBeNull();
  });

  it("shows the server's own ad setting when it sent one, even none", () => {
    expect(adText(AUDIENCE_CLEAR)).toBe("Ages 35–44, women");
    expect(adText({ ...AUDIENCE_CLEAR, ad: "Ages 35–44, all genders (the lean toward women is mild)" })).toBe(
      "Ages 35–44, all genders (the lean toward women is mild)",
    );
    expect(adText(AUDIENCE_EVEN)).toBeNull();
    expect(adText({ ...AUDIENCE_EVEN, ad: undefined })).toBeNull();
  });

  it("reads each band's lean in words, from the server's 0.1 either side of everyone", () => {
    expect(leanWord(0.64)).toBe("more");
    expect(leanWord(0.1)).toBe("more");
    expect(leanWord(-0.42)).toBe("fewer");
    expect(leanWord(0.09)).toBe("even");
    expect(leanWord(-0.09)).toBe("even");
    expect(bandsText(AUDIENCE_CLEAR)).toBe(
      "Under 25: fewer than everyone; 25–29: about like everyone; 30–34: about like everyone; 35–44: more than everyone; " +
        "45–54: about like everyone; 55+: fewer than everyone",
    );
  });

  it("marks the bands the named age group covers: the clearest, and the neighbours that lean too", () => {
    expect([...namedBands(AUDIENCE_CLEAR)]).toEqual(["35–44"]);
    const wide = { ...AUDIENCE_CLEAR, ages: "30–54", bands: AUDIENCE_CLEAR.bands.map((b) => (b.band === "30–34" || b.band === "45–54" ? { ...b, lean: 0.2 } : b)) };
    expect([...namedBands(wide)]).toEqual(["30–34", "35–44", "45–54"]);
    expect(namedBands(AUDIENCE_EVEN).size).toBe(0);
    expect(namedBands({ ...AUDIENCE_CLEAR, ages: null }).size).toBe(0);
  });

  it("draws each bar from the middle: right for more, left for fewer, never past the track", () => {
    expect(barSpan(0.64)).toEqual({ left: 50, width: 32 });
    expect(barSpan(-0.42)).toEqual({ left: 29, width: 21 });
    expect(barSpan(0)).toEqual({ left: 50, width: 0 });
    expect(barSpan(3)).toEqual({ left: 50, width: 50 });
    expect(barSpan(-3)).toEqual({ left: 0, width: 50 });
    expect(barSpan(Number.NaN)).toEqual({ left: 50, width: 0 });
  });
});

describe("a chain's own stores", () => {
  it("says a count that hit the limit as 50+", () => {
    expect(chainLine(CHAIN)).toBe(CHAIN.line);
    // The live server already says "50+" (and "150+" for the wider area): left as it is.
    expect(chainLine(CHAIN_CAPPED)).toBe(CHAIN_CAPPED.line);
    expect(chainLine({ ...CHAIN_CAPPED, line: "50 Starbucks locations are already inside the 15-minute drive." })).toBe(
      "50+ Starbucks locations are already inside the 15-minute drive.",
    );
    // A number that is part of another one stays.
    expect(chainLine({ ...CHAIN_CAPPED, line: "At least 150 stores nearby." })).toBe("At least 150 stores nearby.");
  });
});

describe("the places already inside, against the loved ones", () => {
  it("sets the two rows on one scale and one band order, named for the area", () => {
    const inside = AUDIENCE_TIP.inside;
    if (!inside) throw new Error("the fixture has the places already inside");
    const [loved, there] = compareRows(AUDIENCE_TIP, inside, "10-minute walk");
    expect(loved?.name).toBe("The places people here love");
    expect(there?.name).toBe("Already inside the 10-minute walk");
    expect(there?.bands.map((b) => b.band)).toEqual(AUDIENCE_TIP.bands.map((b) => b.band));
    expect([...(loved?.named ?? [])]).toEqual(["30–34", "35–44"]);
    expect([...(there?.named ?? [])]).toEqual(["45–54", "55+"]);
  });

  it("reads the inside row in the loved row's band order, a missing band as like everyone", () => {
    const inside = AUDIENCE_INSIDE.inside;
    if (!inside) throw new Error("the fixture has the places already inside");
    // Sent in another order, and without 55+.
    const shuffled = { ...inside, bands: [...inside.bands].reverse().slice(1) };
    const [, there] = compareRows(AUDIENCE_INSIDE, shuffled, "10 km drive");
    expect(there?.bands).toEqual([
      { band: "Under 25", lean: 0.04 },
      { band: "25–29", lean: 0.14 },
      { band: "30–34", lean: 0.18 },
      { band: "35–44", lean: -0.03 },
      { band: "45–54", lean: -0.12 },
      { band: "55+", lean: 0 },
    ]);
    expect([...(there?.named ?? [])]).toEqual(["25–29", "30–34"]);
    expect(there?.name).toBe("Already inside the 10 km drive");
  });

  it("says a name that comes up more than once (a chain's branches) once, with its count", () => {
    expect(namesOnce(["Costa Coffee", "Cilantro", "Costa Coffee", "Starbucks", "Costa Coffee"])).toEqual([
      "Costa Coffee (3 places)",
      "Cilantro",
      "Starbucks",
    ]);
    expect(namesOnce(["Burger Yard", "Grill 26"])).toEqual(["Burger Yard", "Grill 26"]);
    expect(namesOnce([])).toEqual([]);
  });
});

describe("the audience's title and the launch plan's note", () => {
  it("calls a category's audience everywhere what it is", () => {
    expect(audienceTitle(AUDIENCE_LIVE)).toBe("Who you'd win");
    expect(audienceTitle(AUDIENCE_GENERAL)).toBe("Who this kind of place draws");
  });

  it("points the channels to the sheet's audience, or says it when the sheet does not show it", () => {
    expect(peopleNote(AUDIENCE_LIVE, false)).toBe(AUDIENCE_LIVE.line);
    expect(peopleNote(AUDIENCE_LIVE, true)).toBe(
      "The ages and gender in these settings follow who the loved places draw, shown above.",
    );
    expect(peopleNote(AUDIENCE_GENERAL, true)).toBe(
      "The ages and gender in these settings follow who this kind of place draws in general, shown above.",
    );
    expect(peopleNote(AUDIENCE_EVEN, true)).toBe(
      "No age or gender stands out in who the loved places draw, so these settings leave both open.",
    );
  });
});
