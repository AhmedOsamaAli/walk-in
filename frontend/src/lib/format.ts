import type { AgentPayload, Focus, GapRow, ReplayPayload, Standing, TopicGroup } from "../api/types";

export const FOCUS_LABELS: Record<Focus, string> = {
  any: "Any business",
  food_drink: "Food & drink",
  retail: "Retail",
  leisure: "Leisure",
};

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

/** Only https images and inline raster data URLs are shown; anything else could be a tracking or script URL. */
export function safeUrl(url: unknown): string | null {
  return typeof url === "string" && (/^https:\/\//i.test(url) || /^data:image\/(png|jpeg|webp);base64,/i.test(url))
    ? url
    : null;
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
