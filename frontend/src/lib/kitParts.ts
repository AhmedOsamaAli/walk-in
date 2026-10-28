/**
 * The launch kit's parts, as its page's tabs show them: the poster for the window first, then what goes out with it,
 * the report for a landlord or a lender, and last Founders, where the neighbors back the business before it opens.
 */
export const KIT_PARTS = [
  { id: "poster", label: "Poster" },
  { id: "copy", label: "Ad copy" },
  { id: "links", label: "Links" },
  { id: "report", label: "Report" },
  { id: "founders", label: "Founders" },
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
