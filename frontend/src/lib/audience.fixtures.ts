/* Test data: audiences with and without a clear lean, the places already inside against the loved ones (with and
   without the tip), and a chain's stores, counted and capped. */
import type { Audience, ChainCheck } from "../api/types";

export const AUDIENCE_CLEAR: Audience = {
  ages: "35–44",
  age_min: 35,
  age_max: 44,
  gender: "women",
  bands: [
    { band: "Under 25", lean: -0.42 },
    { band: "25–29", lean: -0.08 },
    { band: "30–34", lean: 0.04 },
    { band: "35–44", lean: 0.64 },
    { band: "45–54", lean: 0.06 },
    { band: "55+", lean: -0.35 },
  ],
  gender_lean: 0.38,
  places: ["Harbor Oyster Bar", "Dockside Crab", "Saltwater Kitchen"],
  line: "The 5 seafood places people here love draw 35–44-year-olds most, and lean toward women.",
  basis:
    "Qloo's audience data for the 5 seafood places people here love: how much more or less each age group and gender " +
    "engages with them than everyone does, the median over those places. Leans, not head counts.",
};

export const AUDIENCE_EVEN: Audience = {
  ages: null,
  age_min: null,
  age_max: null,
  gender: null,
  bands: [
    { band: "Under 25", lean: 0.06 },
    { band: "25–29", lean: -0.04 },
    { band: "30–34", lean: 0.09 },
    { band: "35–44", lean: -0.02 },
    { band: "45–54", lean: 0.03 },
    { band: "55+", lean: -0.07 },
  ],
  gender_lean: 0.05,
  places: ["Harbor Oyster Bar", "Dockside Crab", "Saltwater Kitchen"],
  line:
    "The 5 seafood places people here love draw every age group and both women and men about equally: no need to " +
    "narrow an ad by either.",
  basis:
    "Qloo's audience data for the 5 seafood places people here love: how much more or less each age group and gender " +
    "engages with them than everyone does, the median over those places. Leans, not head counts.",
  ad: null,
};

/** The line and the ad from a live run (Zamalek, a 10 km drive, hamburgers); the leans are set to agree with them. */
export const AUDIENCE_LIVE: Audience = {
  ages: "30–34",
  age_min: 30,
  age_max: 34,
  gender: "men",
  bands: [
    { band: "Under 25", lean: 0.05 },
    { band: "25–29", lean: 0.08 },
    { band: "30–34", lean: 0.22 },
    { band: "35–44", lean: 0.02 },
    { band: "45–54", lean: -0.18 },
    { band: "55+", lean: -0.31 },
  ],
  gender_lean: -0.19,
  places: ["Burger Yard", "Grill 26", "The Patty Shop", "Nile Burger Co", "Zamalek Smash"],
  line: "The 5 hamburger places people here love draw 30–34-year-olds most, and lean toward men.",
  basis:
    "Qloo's audience data for the 5 hamburger places people here love: how much more or less each age group and " +
    "gender engages with them than everyone does, the median over those places. Leans, not head counts.",
  ad: "Ages 30–34, all genders (the lean toward men is mild)",
};

/** Too few of the loved places had audience data: the category everywhere, said as such. */
export const AUDIENCE_GENERAL: Audience = {
  ...AUDIENCE_LIVE,
  places: [],
  line: "Hamburger places in general draw 30–34-year-olds most, and lean toward men.",
  basis:
    "Qloo's audience data for hamburger places in general, everywhere: too few of the places people here love of this " +
    "kind have their own. How much more or less each age group and gender engages with them than everyone does. " +
    "Leans, not head counts.",
  general: true,
};

/** Rare on real data: the loved places draw 30–44 and women, the 6 already inside 45+ and men. */
export const AUDIENCE_TIP: Audience = {
  ages: "30–44",
  age_min: 30,
  age_max: 44,
  gender: "women",
  bands: [
    { band: "Under 25", lean: -0.28 },
    { band: "25–29", lean: -0.06 },
    { band: "30–34", lean: 0.31 },
    { band: "35–44", lean: 0.38 },
    { band: "45–54", lean: -0.09 },
    { band: "55+", lean: -0.33 },
  ],
  gender_lean: 0.36,
  places: ["Burger Yard", "Grill 26", "The Patty Shop", "Nile Burger Co", "Zamalek Smash"],
  line: "The 5 hamburger places people here love draw 30–44-year-olds most, and lean toward women.",
  basis: AUDIENCE_LIVE.basis,
  ad: "Ages 30–44, women",
  inside: {
    ages: "45+",
    gender: "men",
    gender_lean: -0.34,
    bands: [
      { band: "Under 25", lean: -0.35 },
      { band: "25–29", lean: -0.22 },
      { band: "30–34", lean: -0.12 },
      { band: "35–44", lean: -0.02 },
      { band: "45–54", lean: 0.27 },
      { band: "55+", lean: 0.41 },
    ],
    places: ["Burger Station", "Corner Burger", "Patty Palace", "The Bun House", "Smash Street", "Grill Nearby"],
  },
  tip:
    "The 6 hamburger places already inside the walk draw people 45 and over and lean toward men. The ones people here " +
    "love draw 30–44-year-olds, leaning toward women: aim the concept at them.",
};

/** The places already inside draw much the same people as the loved ones: the second row, and no tip. */
export const AUDIENCE_INSIDE: Audience = {
  ...AUDIENCE_LIVE,
  inside: {
    ages: "25–34",
    gender: null,
    gender_lean: -0.06,
    bands: [
      { band: "Under 25", lean: 0.04 },
      { band: "25–29", lean: 0.14 },
      { band: "30–34", lean: 0.18 },
      { band: "35–44", lean: -0.03 },
      { band: "45–54", lean: -0.12 },
      { band: "55+", lean: -0.24 },
    ],
    places: ["Burger Station", "Corner Burger", "Patty Palace", "The Bun House"],
  },
  tip: null,
};

export const CHAIN: ChainCheck = {
  brand: "Starbucks",
  inside: 1,
  around: 4,
  capped: false,
  line: "1 Starbucks location is already inside the 10-minute walk, and 4 within a 20-minute walk.",
  basis: "Qloo's places that carry the Starbucks brand, counted inside the 10-minute walk and within a 20-minute walk.",
};

export const CHAIN_CAPPED: ChainCheck = {
  brand: "Starbucks",
  inside: 50,
  around: 150,
  capped: true,
  line: "50+ Starbucks locations are already inside the 15-minute drive, and 150+ within a 30-minute drive.",
  basis: "Qloo's places that carry the Starbucks brand, counted inside the 15-minute drive and within a 30-minute drive.",
};
