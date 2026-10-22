import type {
  AgentPayload,
  Focus,
  GapRow,
  Intent,
  Kitchen,
  ReplayPayload,
  Standing,
  TopicGroup,
  VerdictLevel,
} from "../api/types";

export const FOCUS_LABELS: Record<Focus, string> = {
  any: "Any business",
  food_drink: "Food & drink",
  retail: "Retail",
  leisure: "Leisure",
};

/** The three things an owner can ask, with what each survey does and its one action. */
export const INTENTS: Record<Intent, { label: string; does: string; action: string }> = {
  explore: {
    label: "Find what fits",
    does: "Ranks what the block is missing and designs the three businesses with the strongest evidence.",
    action: "Survey this site",
  },
  open: {
    label: "Open a business",
    does: "Judges the business you have in mind against everything the block is missing, then designs it to win here.",
    action: "Judge this idea",
  },
  improve: {
    label: "Improve my place",
    does: "Compares the place you run with the ones locals love in its category and lists what to change.",
    action: "Compare my place",
  },
};

export const KITCHEN_LABELS: Record<Kitchen, string> = {
  full: "Full kitchen with extraction",
  light: "Light prep, no hood",
  none: "No kitchen",
};

/** The verdict on the owner's idea, as its stamp reads. */
export const VERDICT_STAMPS: Record<VerdictLevel, string> = {
  strong: "Strong fit",
  possible: "Possible",
  weak: "Weak",
  thin: "Thin data",
  misfit: "Doesn't fit",
  unknown: "Not on Qloo",
};

export const SQ_FT_M2 = 0.092903;

/** The unit's floor area in m², from what the owner typed in m² or ft²; null when empty or outside 10–2000 m². */
export function floorArea(text: string, unit: "m2" | "ft2"): number | null {
  const value = Number(text.replace(",", "."));
  if (!text.trim() || !Number.isFinite(value) || value <= 0) return null;
  const m2 = unit === "ft2" ? value * SQ_FT_M2 : value;
  return m2 >= 10 && m2 <= 2000 ? Math.round(m2 * 10) / 10 : null;
}

/** "650 m" or "1.2 km". */
export function distanceText(meters: number | null | undefined): string {
  if (meters == null) return "";
  return meters < 950 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`;
}

export const fmtLat = (lat: number) => `${lat >= 0 ? "N" : "S"} ${Math.abs(lat).toFixed(4)}`;
export const fmtLon = (lon: number) => `${lon >= 0 ? "E" : "W"} ${Math.abs(lon).toFixed(4)}`;
export const coords = (lat: number, lon: number) => `${fmtLat(lat)} · ${fmtLon(lon)}`;
export const letter = (index: number) => String.fromCharCode(65 + index);

/** "$" to "$$$$"; anything unreadable counts as mid-range. */
export function price(level: unknown): string {
  return "$".repeat(Math.max(1, Math.min(4, Number(level) || 2)));
}

const PRICE_WORDS = ["", "inexpensive", "moderate", "pricey", "high-end"];

/** "$$ · moderate", or "" when Qloo lists no price: an unknown price is never shown as a guess. */
export function priceLabel(level: number | null | undefined): string {
  return level && level >= 1 && level <= 4 ? `${"$".repeat(level)} · ${PRICE_WORDS[level]}` : "";
}

/** Seconds as the log shows them: "4.2s". */
export const secondsText = (seconds: number) => `${seconds.toFixed(1)}s`;

/** Why a place is established, as a badge: "Michelin 1 star", "Michelin listed" or "1,563 reviews". */
export function standingText(standing: Standing | null | undefined): string {
  if (!standing) return "";
  if (standing.michelin) return `Michelin ${standing.michelin}`;
  return standing.reviews ? `${standing.reviews.toLocaleString("en-US")} reviews` : "";
}

/** The other ways reviews word a topic, beyond its label: "long lines, wait time, on line". */
export function topicForms(group: TopicGroup, limit = 3): string[] {
  const label = group.label.toLowerCase();
  return group.keywords.filter((keyword) => keyword.toLowerCase() !== label).slice(0, limit);
}

/** Agent-written lists can arrive as a single string or with empty entries. */
export function list(value: unknown): string[] {
  const items: unknown[] = Array.isArray(value) ? value : value ? [value] : [];
  return items
    .filter((item): item is string | number => typeof item === "string" || typeof item === "number")
    .map(String)
    .filter((item) => item.trim() !== "");
}

/** ["a", "b", "c"] -> "a, b and c". */
export function naturalList(items: string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1] ?? ""}` : (items[0] ?? "");
}

/** Only https images and inline raster data URLs are shown; anything else could be a tracking or script URL. */
export function safeUrl(url: unknown): string | null {
  return typeof url === "string" && (/^https:\/\//i.test(url) || /^data:image\/(png|jpeg|webp);base64,/i.test(url))
    ? url
    : null;
}

/** A link to a place's own website or menu: http or https only, so no script URL can ever be opened. */
export function safeLink(url: unknown): string | null {
  if (typeof url !== "string") return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** "Fort Greene, Brooklyn, Kings County, New York" -> "Fort Greene, Brooklyn". */
export function shortLabel(label: string | null | undefined): string {
  const parts = (label ?? "").split(",").map((part) => part.trim()).filter(Boolean);
  return parts.slice(0, 2).join(", ") || "Selected site";
}

/** The gap's evidence in one plain sentence. */
export function gapWhy(gap: GapRow): string {
  const parts: string[] = [];
  if (gap.lift >= 0.5) parts.push("loved more here than in the areas around");
  else if (gap.lift <= -0.3) parts.push("loved less here than around");
  if (gap.relative_supply <= 0.8) parts.push("fewer places than a block this dense usually has");
  else if (gap.relative_supply >= 1.4) parts.push("already well supplied");
  if (gap.leakage != null && gap.leakage >= 0.65) parts.push("locals travel for their own favorites");
  else if (gap.leakage != null && gap.leakage <= 0.4) parts.push("locals' own favorites are already close by");
  if (gap.evidence === "thin") parts.push("Qloo knows too few places of this type here to judge");
  if (gap.evidence === "atypical") parts.push("favorites are mostly hotels or malls");
  const text = parts.join("; ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : "Demand and supply look typical for this block.";
}

function argText(args: AgentPayload["args"], key: string): string | null {
  const value = args?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function agentText({ tool, args }: AgentPayload): string {
  const reasonText = argText(args, "reason");
  const reason = reasonText ? ` — ${reasonText}` : "";
  if (tool === "inspect_gap") return `Agent inspects the ${argText(args, "genre") ?? "unknown"} gap${reason}`;
  if (tool === "test_category") {
    return `Agent tests a hunch live on Qloo: ${argText(args, "category") ?? "a new category"}${reason}`;
  }
  if (tool === "fan_taste") {
    return `Agent asks Qloo what local fans of ${argText(args, "category") ?? "this category"} also love${reason}`;
  }
  return `Agent calls ${tool}${reason}`;
}

export function replayText({ saved_at: savedAt, model }: ReplayPayload): string {
  const when = savedAt
    ? new Date(savedAt * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "earlier";
  return `Same Qloo evidence as a survey on ${when}: replaying that agent run${model ? ` (${model})` : ""} to save the free AI quota`;
}

export function agentCredit(model: string | null | undefined, replayedFrom: number | null | undefined): string {
  if (!model) return "the agent";
  return replayedFrom ? `the agent (${model}, replayed)` : `the agent (${model})`;
}
