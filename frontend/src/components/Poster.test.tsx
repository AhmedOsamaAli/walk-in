import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Concept } from "../api/types";
import { PAIR_WILD, REALITY_TITLES, REALITY_TV, THEMED_PLAIN, THEMED_WILD } from "../lib/wildTheme.fixtures";
import { Poster } from "./Poster";

const card = (concept: Concept, rank: number | null = null) =>
  renderToStaticMarkup(<Poster concept={concept} index={3} rank={rank} position={3} onOpen={() => undefined} />);

/** The pair wild card as Poster drew it before themes came, child by child: a survey made then must look as it did. */
const PAIR_CARD = [
  '<article class="poster wild" style="--i:3" aria-labelledby="poster-3-name">',
  '<div class="poster-top mono"><span>Wild card · not ranked</span></div>',
  '<div class="poster-head"><span class="stamp untested mono">Untested</span><h3 class="poster-name" id="poster-3-name">Redfish &amp; Rhythm</h3></div>',
  '<div class="poster-pair"><p class="poster-combines"><span class="mono">Combines</span> <b>seafood places</b><span aria-hidden="true"> × </span><span class="sr-only"> and </span><b>live music venues</b></p><ul class="poster-loves"><li><b>Seafood places:</b> People here rank seafood #7 among place types, higher than the areas around (#12) (Qloo).</li><li><b>Live music venues:</b> People here rank live music venue #1 among the place types they engage with (Qloo).</li></ul></div>',
  '<p class="poster-line">A lively seafood hall and music space serving coastal Texas dishes alongside nightly live music performances.</p>',
  '<p class="poster-note poster-caution"><b class="mono">Caution</b>Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on two separate loves.</p>',
  '<div class="poster-sig"><span>Texas redfish pontchartrain</span><span>Sweet potato pecan pie</span><span>Gulf oysters on the half shell</span></div>',
  '<p class="poster-note"><b class="mono">Competition</b>No place inside the 15-minute drive is both; the nearest competition is the 69 seafood places and the 49 live music venues inside the 15-minute drive, each doing one half.</p>',
  '<div class="poster-note poster-rules"><b class="mono">Your rules</b><ul><li>Budget prices: nothing in it is called upscale or premium.</li></ul></div>',
  '<p class="poster-insp mono">Inspired by Pappadeaux Seafood Kitchen · Mongers · Mohawk Austin</p>',
  '<button id="poster-3-open" class="poster-open mono" type="button" aria-label="Open design sheet: Redfish &amp; Rhythm"><span>Open design sheet</span><span aria-hidden="true">→</span></button>',
  "</article>",
].join("");

const titlesOf = (html: string) => [...html.matchAll(/<li class="theme-title">(.*?)<\/li>/g)].map((match) => match[1]);

describe("a wild card from before themes", () => {
  it("is drawn exactly as it was", () => {
    expect(card(PAIR_WILD)).toBe(PAIR_CARD);
  });
});

describe("a themed wild card", () => {
  const html = card(THEMED_WILD);

  it("says what it is, stays untested, and combines the kind of place with the theme", () => {
    expect(html).toMatch(/^<article class="poster wild themed"/);
    expect(html).toContain('<div class="poster-top mono"><span>Themed wild card · not ranked</span></div>');
    expect(html).toContain('<span class="stamp untested mono">Untested</span>');
    expect(html).toContain(
      '<b>cocktail bars</b><span aria-hidden="true"> × </span><span class="sr-only"> and </span><b>reality TV</b>',
    );
    // The kind of place keeps its evidence; the theme's evidence is its titles.
    expect(html).toContain("<li><b>Cocktail bars:</b> People here rank cocktail bars #6 among place types");
    expect(html).not.toContain("<b>Reality TV:</b>");
  });

  it("shows four of the titles it is built on: Qloo's picture, loaded lazily without a referrer, the name, what it is", () => {
    const titles = titlesOf(html);
    expect(titles).toHaveLength(4);
    expect(html).not.toContain("Scrubbing In");
    const [first] = titles;
    expect(first).toMatch(/^<span class="theme-pic"><img [^>]*\/><\/span>/);
    expect(first).toContain(`src="${String(REALITY_TITLES[0]?.image)}"`);
    for (const attribute of ['alt=""', 'loading="lazy"', 'decoding="async"', /referrerPolicy="no-referrer"/i]) {
      expect(first).toMatch(attribute);
    }
    expect(first).toContain(
      '<span class="theme-name">Jersey Shore: Family Vacation</span><span class="theme-domain mono"><span class="sr-only">, </span>TV</span>',
    );
    expect(titles.map((title) => /(TV|Podcast)<\/span>$/.exec(title ?? "")?.[1])).toEqual(["TV", "TV", "Podcast", "Podcast"]);
  });

  it("names the strip of titles for a screen reader", () => {
    const label = /<p class="theme-label mono" id="([^"]+)">Built on what people here over-index on<\/p>/.exec(html);
    expect(label?.[1]).toBeTruthy();
    expect(html).toContain(`<ul class="theme-titles" aria-labelledby="${label?.[1] ?? ""}">`);
  });

  it("says what happens there and who the titles draw, then the card's own lines", () => {
    for (const line of REALITY_TV.program) expect(html).toContain(`<li>${line}</li>`);
    expect(html).toContain(
      '<p class="theme-draws"><b class="theme-label mono">Draws</b>Ages 25–34 most · leans toward women<small>Qloo audience leans of these titles&#x27; fans: leans, not head counts.</small></p>',
    );
    const order = ["Built on what people here", "What happens there", ">Draws<", "poster-line", ">Caution<", ">Competition<", "Open design sheet"];
    const at = order.map((text) => html.indexOf(text));
    expect(at.every((index) => index >= 0)).toBe(true);
    expect(at).toEqual([...at].sort((a, b) => a - b));
  });
});

describe("a themed wild card without pictures or an audience lean", () => {
  it("shows each title's initials in its square, and no Draws line", () => {
    const html = card(THEMED_PLAIN);
    expect(html).not.toContain("<img");
    expect(titlesOf(html).map((title) => /aria-hidden="true">([^<]*)</.exec(title ?? "")?.[1])).toEqual(["JS", "C", "OT"]);
    expect(html).toContain("What happens there");
    expect(html).not.toContain("Draws");
  });

  it("loads only pictures served over https", () => {
    const http = { ...REALITY_TV, built_on: [{ domain: "tv" as const, id: "x", name: "Cheer", image: "http://images.qloo.com/i/x.jpg" }] };
    expect(card({ ...THEMED_WILD, theme: http })).not.toContain("<img");
  });
});

it("leaves the theme off a ranked concept: only the wild card is themed", () => {
  const html = card({ ...THEMED_WILD, wildcard: false, gap_score: 51 }, 1);
  expect(html).toContain("<span>Concept D · Cocktail Bar</span>");
  expect(html).not.toContain("theme-");
});
