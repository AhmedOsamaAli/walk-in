/**
 * The launch kit's parts, as its page's tabs show them: the poster for the window first, then what goes out with it,
 * and the report for a landlord or a lender last. Each says what it holds on the way in from the part before.
 */
export const KIT_PARTS = [
  { id: "poster", label: "Poster", teaser: "A poster for the window, drawn on the streets around the site, ready to print." },
  { id: "copy", label: "Ad copy", teaser: "One ad for each channel of the launch plan, every line checked against the evidence." },
  { id: "links", label: "Links", teaser: "Tracked links to your own page, one per channel, to see which one brings people in." },
  { id: "report", label: "Report", teaser: "The case for this business, for a landlord or a lender, ready to save as a PDF." },
] as const;

export type KitPart = (typeof KIT_PARTS)[number]["id"];

/** The part an id names, or null. */
export function kitPart(id: string): KitPart | null {
  return KIT_PARTS.find((part) => part.id === id)?.id ?? null;
}

/** The part an address's hash names: "#links", or "#kit-links" as the page's old section links had it; else null. */
export function partInHash(hash: string): KitPart | null {
  return kitPart(hash.replace(/^#(kit-)?/, ""));
}
