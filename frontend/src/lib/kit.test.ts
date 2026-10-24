import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { LaunchPlan } from "../api/types";
import { absoluteUrl, cssString, kitChannels, kitError, linkKind, qrPath, reportPageCss, scanCaption, shortLink, trackedUrl, travelLetters, websiteUrl } from "./kit";

function plan(channels: string[]): LaunchPlan {
  return {
    audience: { crowd: [], artists: [], podcasts: [], screen: [], brands: [], shared: [] },
    where: { minutes: 10, reach_m: 556, neighborhoods: [], sites_like: [] },
    when: { times: [], intents: [] },
    claims: [],
    channels: channels.map((channel) => ({ channel, setting: "x", why: "y" })),
    cautions: [],
  };
}

describe("the kit's channels", () => {
  it("writes one piece per channel of the plan, and always the poster", () => {
    const all = ["Meta or Google local ads", "Spotify Ads", "Nextdoor", "Google Ads custom segment"];
    expect(kitChannels(plan(all))).toEqual(["spotify", "nextdoor", "google_search", "meta", "poster"]);
    expect(kitChannels(plan(["Spotify Ads", "Meta or Google local ads", "Somewhere new"]))).toEqual(["spotify", "meta", "poster"]);
    expect(kitChannels(null)).toEqual(["poster"]);
  });
});

describe("poster lines", () => {
  it("prints a link without its scheme and tags", () => {
    expect(shortLink("https://www.goldenhour.cafe/?utm_source=poster")).toBe("goldenhour.cafe");
    expect(shortLink("https://goldenhour.cafe/menu/?utm_source=poster")).toBe("goldenhour.cafe/menu");
    expect(shortLink("not a url")).toBe("not a url");
  });

  it("says over the QR code where it leads, as much of that as fits", () => {
    const measure = (line: string) => line.length * 6;
    const url = "https://www.goldenhour.cafe/menu/?utm_source=poster";
    expect(scanCaption(url, 200, measure)).toBe("SCAN · GOLDENHOUR.CAFE/MENU");
    expect(scanCaption(url, 140, measure)).toBe("SCAN · GOLDENHOUR.CAFE");
    expect(scanCaption("https://walk-in-aoa2.onrender.com/s/d0d869287ed6?sheet=0", 130, measure)).toBe("SCAN WITH YOUR CAMERA");
    expect(scanCaption(url, 20, measure)).toBe("SCAN");
  });
});

describe("tracked links", () => {
  it("reads the owner's link, adding the scheme they left out: any http(s) page of theirs", () => {
    expect(websiteUrl("goldenhour.cafe")).toBe("https://goldenhour.cafe/");
    expect(websiteUrl(" https://goldenhour.cafe/menu?x=1 ")).toBe("https://goldenhour.cafe/menu?x=1");
    expect(websiteUrl("http://localhost:8000")).toBe("http://localhost:8000/");
    expect(websiteUrl("instagram.com/goldenhour")).toBe("https://instagram.com/goldenhour");
    expect(websiteUrl("wa.me/201001234567")).toBe("https://wa.me/201001234567");
    expect(websiteUrl("https://maps.app.goo.gl/AbC123")).toBe("https://maps.app.goo.gl/AbC123");
    for (const text of ["", "golden hour", "javascript:alert(1)", "ftp://goldenhour.cafe", "goldenhour"]) {
      expect(websiteUrl(text)).toBeNull();
    }
  });

  it("names the kind of page a link opens, so the page can say whether its tags can be read", () => {
    expect(linkKind("https://goldenhour.cafe/")).toBe("website");
    expect(linkKind("https://www.instagram.com/goldenhour/")).toBe("instagram");
    expect(linkKind("https://m.facebook.com/goldenhour")).toBe("facebook");
    expect(linkKind("https://wa.me/201001234567")).toBe("whatsapp");
    expect(linkKind("https://api.whatsapp.com/send?phone=201001234567")).toBe("whatsapp");
    expect(linkKind("https://maps.app.goo.gl/AbC123")).toBe("maps");
    expect(linkKind("https://www.google.com/maps/place/Golden+Hour")).toBe("maps");
    expect(linkKind("https://www.google.com/search?q=golden+hour")).toBe("website");
    expect(linkKind("https://notinstagram.com/goldenhour")).toBe("website");
    expect(linkKind("not a url")).toBe("website");
  });

  it("adds a channel's tags to the landing page", () => {
    const query = "utm_source=poster&utm_medium=qr&utm_campaign=golden-hour-launch";
    expect(trackedUrl("https://goldenhour.cafe/", query)).toBe(`https://goldenhour.cafe/?${query}`);
    expect(trackedUrl("https://goldenhour.cafe/menu?lang=en#top", query)).toBe(`https://goldenhour.cafe/menu?lang=en&${query}#top`);
    expect(trackedUrl("https://goldenhour.cafe/?utm_source=old", query)).toBe(`https://goldenhour.cafe/?${query}`);
    expect(absoluteUrl("/s/r1?sheet=0", "https://walk-in.example")).toBe("https://walk-in.example/s/r1?sheet=0");
  });
});

describe("the QR code", () => {
  it("encodes a link as a square of modules", () => {
    const { size, path } = qrPath("https://goldenhour.cafe/?utm_source=poster&utm_medium=qr&utm_campaign=golden-hour-launch");
    expect(size).toBeGreaterThanOrEqual(21);
    expect((size - 17) % 4).toBe(0);
    expect(path.startsWith("M0 0h1v1h-1z")).toBe(true);
    expect(qrPath("https://goldenhour.cafe/").path).not.toBe(path);
  });
});

describe("making a kit", () => {
  it("says why a kit could not be made in plain words", () => {
    expect(kitError(new ApiError("Too many kits from this address. Try again in an hour.", 429, true), "x")).toBe(
      "Too many kits from this address. Try again in an hour.",
    );
    expect(kitError(new ApiError("Too many requests. Try again in a while.", 429), "x")).toBe(
      "Too many kits were started from this address just now. Try again in a little while.",
    );
    expect(kitError(new ApiError("Survey or concept not found. Run the site again.", 404, true), "x")).toBe(
      "Survey or concept not found. Run the site again.",
    );
    expect(kitError(new TypeError("Failed to fetch"), "x")).toBe("Walk-in can't be reached. Check your connection and try again.");
    expect(kitError(new Error("boom"), "The kit could not be started.")).toBe("The kit could not be started.");
  });
});

describe("the report's paper", () => {
  it("sets any name as a CSS string that cannot end its rule", () => {
    expect(cssString("Golden Hour")).toBe('"Golden Hour"');
    expect(cssString('Tide "&" Table')).toBe('"Tide \\"&\\" Table"');
    expect(cssString("Back\\slash")).toBe('"Back\\\\slash"');
    expect(cssString("Two\nlines\u0000}")).toBe('"Two lines }"');
    expect(cssString('"; } body { display: none } @page { content: "')).toBe(
      '"\\"; } body { display: none } @page { content: \\""',
    );
  });

  it("runs the business's name and the page count in fixed margins, but not on the cover", () => {
    const css = reportPageCss('Copper "K" Kitchen', "Prepared with Walk-in on Oct 23, 2026");
    expect(css).toContain("@page report {");
    expect(css).toContain("margin: 20mm 18mm 18mm 18mm;");
    expect(css).toContain('@top-left { content: "Copper \\"K\\" Kitchen";');
    expect(css).toContain('@top-right { content: "Walk-in report";');
    expect(css).toContain('@bottom-left { content: "Prepared with Walk-in on Oct 23, 2026";');
    expect(css).toContain('content: "Page " counter(page) " of " counter(pages);');
    expect(css).toMatch(/@page report:first \{\s+@top-left \{ content: none; \}\s+@top-right \{ content: none; \}\s+\}/);
    // Chromium ignores custom properties inside @page: every value is written out.
    expect(css).not.toContain("var(");
  });
});

describe("the travel list's letters", () => {
  const places = [{ name: "Trio Cafe" }, { name: "Kajja" }, { name: "Mezzanine" }, { name: "Vinni Cafe" }];

  it("gives each place the letter the cover map gives its trip", () => {
    const trips = ["A", "B", "C", "D"].map((key, index) => ({ key, name: places[index]?.name ?? "" }));
    expect(travelLetters(places, trips)).toEqual(["A", "B", "C", "D"]);
  });

  it("leaves a place off the map without a letter, and the others keep theirs", () => {
    const trips = [
      { key: "A", name: "Trio Cafe" },
      { key: "C", name: "Mezzanine" },
      { key: "D", name: "Vinni Cafe" },
    ];
    expect(travelLetters(places, trips)).toEqual(["A", null, "C", "D"]);
  });

  it("gives no letters without a map, or when a trip names another place", () => {
    expect(travelLetters(places, [])).toEqual([null, null, null, null]);
    expect(travelLetters(places, [{ key: "A", name: "Somewhere else" }])).toEqual([null, null, null, null]);
  });
});
