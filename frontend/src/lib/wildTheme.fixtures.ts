/* Test data: a wild card as surveys made it before themes (two loves combined), and themed wild cards built on what
   people in East Austin over-index on, with and without Qloo's pictures and the audience lean of their fans. The
   titles, ids and pictures are East Austin's own; the rest is written the way the server writes it. */
import type { Concept, ConceptTheme, ThemeCard } from "../api/types";

const CAUTION =
  "Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on two separate loves.";

/** East Austin's wild card as its survey recorded it, with an owner's rule added. */
export const PAIR_WILD: Concept = {
  name: "Redfish & Rhythm",
  genre: "Seafood",
  genre_id: "urn:tag:genre:place:restaurant:seafood",
  gap_score: null,
  wildcard: true,
  combines: [
    {
      item: "seafood places",
      genre: "Seafood",
      source: "People here rank seafood #7 among place types, higher than the areas around (#12) (Qloo).",
    },
    {
      item: "live music venues",
      genre: "Live music venue",
      source: "People here rank live music venue #1 among the place types they engage with (Qloo).",
    },
  ],
  caution: CAUTION,
  one_liner: "A lively seafood hall and music space serving coastal Texas dishes alongside nightly live music performances.",
  for_whom: "People within a 15-minute drive who love both seafood places and live music venues",
  why_here: [
    "People here rank seafood #7 among place types, higher than the areas around (#12).",
    "People here rank live music venue #1 among the place types they engage with.",
  ],
  beat_competitors:
    "No place inside the 15-minute drive is both; the nearest competition is the 69 seafood places and the 49 live music venues inside the 15-minute drive, each doing one half.",
  signature: ["Texas redfish pontchartrain", "Sweet potato pecan pie", "Gulf oysters on the half shell"],
  inspired_by: ["Pappadeaux Seafood Kitchen", "Mongers", "Mohawk Austin", "Carson Creek Ranch"],
  risk: CAUTION,
  owner_rules: ["Budget prices: nothing in it is called upscale or premium."],
};

const picture = (id: string) => `https://images.qloo.com/i/${id}-420x-auto.jpg`;

const TITLES: Omit<ThemeCard, "image">[] = [
  { domain: "tv", id: "2427BA5C-BB92-44E7-B70F-4C08230AC7B8", name: "Jersey Shore: Family Vacation" },
  { domain: "tv", id: "65F63CC6-A0A5-4679-B17D-7D7EB43F63C7", name: "Cheer" },
  { domain: "podcasts", id: "23FF7788-EEFE-461F-B59A-D1559B950B03", name: "Off The Vine with Kaitlyn Bristowe" },
  { domain: "podcasts", id: "8F9F7103-258C-493B-88B4-F6AFB753D05F", name: "The Ben and Ashley I Almost Famous Podcast" },
  { domain: "podcasts", id: "733F2233-2FDC-4A46-9299-1D519C52C852", name: "Scrubbing In with Becca Tilley & Tanya Rad" },
];

/** Five titles people in East Austin over-index on, with Qloo's pictures; a poster shows the first four. */
export const REALITY_TITLES: ThemeCard[] = TITLES.map((card) => ({ ...card, image: picture(card.id) }));

export const REALITY_TV: ConceptTheme = {
  key: "reality_tv",
  label: "reality TV",
  program: [
    "Watch parties for Jersey Shore: Family Vacation and Cheer",
    "Recap nights with the Off The Vine with Kaitlyn Bristowe podcast",
  ],
  built_on: REALITY_TITLES,
  draws: {
    ages: ["25–29", "30–34"],
    gender: "female",
    basis: "Qloo audience leans of these titles' fans: leans, not head counts.",
  },
  basis: "What people within 6.5 km over-index on compared with same-size areas about 20 km away (Qloo).",
};

const UNTESTED =
  "Untested: no place inside the 15-minute drive does this, so there is no direct proof people would come; it is built from what people here watch, hear and follow.";

/** A themed wild card: a kind of place people here love, built around reality TV. */
export const THEMED_WILD: Concept = {
  name: "The Rose Ceremony",
  genre: "Cocktail Bar",
  genre_id: "urn:tag:genre:place:bar:cocktail",
  gap_score: null,
  wildcard: true,
  combines: [
    {
      item: "cocktail bars",
      genre: "Cocktail Bar",
      source: "People here rank cocktail bars #6 among place types, higher than the areas around (#11) (Qloo).",
    },
    {
      item: "reality TV",
      genre: "",
      source:
        "People here over-index on Jersey Shore: Family Vacation, Cheer and Off The Vine with Kaitlyn Bristowe compared with same-size areas around (Qloo).",
    },
  ],
  theme: REALITY_TV,
  caution: UNTESTED,
  one_liner: "A cocktail bar for reality-TV nights: the shows people here follow on the big screen, and the podcasts that recap them.",
  for_whom: "People within a 15-minute drive who love reality TV",
  beat_competitors: "No place inside the 15-minute drive is known for reality TV.",
  signature: ["Watch-party pitchers", "Recap-night flights"],
  risk: UNTESTED,
  owner_rules: [],
};

/** The same card when Qloo had no pictures for its titles and no audience lean for their fans. */
export const THEMED_PLAIN: Concept = {
  ...THEMED_WILD,
  theme: { ...REALITY_TV, built_on: REALITY_TITLES.slice(0, 3).map((card) => ({ ...card, image: null })), draws: null },
};
