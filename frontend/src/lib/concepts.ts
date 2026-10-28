/* The concepts section's rules (ConceptsSection.tsx, Poster.tsx): the order of the cards, the wild card, and what the
   owner's rules changed. */
import type { Concept, ConceptsPayload, LoveItem } from "../api/types";
import { agentCredit, list } from "./format";
import { themeOf } from "./wildTheme";

/**
 * A concept as the section shows it: its index in the payload, which its design sheet and the sheet's link use, and its
 * rank among the ranked concepts; null for the wild card, which is never ranked.
 */
export interface Placed {
  concept: Concept;
  index: number;
  rank: number | null;
}

export const isWildcard = (concept: Concept): boolean => concept.wildcard === true;

/** The ranked concepts in their order, then the wild card, whatever order the payload lists them in. */
export function placeConcepts(concepts: readonly Concept[]): Placed[] {
  const ranked: Placed[] = [];
  const wild: Placed[] = [];
  concepts.forEach((concept, index) => {
    if (isWildcard(concept)) wild.push({ concept, index, rank: null });
    else ranked.push({ concept, index, rank: ranked.length });
  });
  return [...ranked, ...wild];
}

function isLove(value: unknown): value is LoveItem {
  if (typeof value !== "object" || value === null) return false;
  const love = value as Partial<Record<keyof LoveItem, unknown>>;
  return typeof love.item === "string" && love.item.trim() !== "" && typeof love.source === "string";
}

/** The two loves a wild card combines, each named, with its evidence; a themed wild card's second is its theme. */
export function loves(concept: Concept): LoveItem[] {
  const items: unknown[] = Array.isArray(concept.combines) ? concept.combines : [];
  return items.filter(isLove).slice(0, 2);
}

/** "coffee shops × jazz clubs"; empty without two loves. */
export function combinesText(concept: Concept): string {
  const both = loves(concept);
  return both.length === 2 ? both.map((love) => love.item.trim()).join(" × ") : "";
}

/** The concept's risk; a wild card's risk repeats its caution, which the card already says. */
export function riskText(concept: Concept): string | null {
  const risk = concept.risk?.trim();
  if (!risk) return null;
  return isWildcard(concept) && risk === concept.caution?.trim() ? null : risk;
}

/** How the concept keeps each rule the owner gave, one line each. */
export const ruleLines = (concept: Concept): string[] => list(concept.owner_rules).map((line) => line.trim());

/** What was dropped or changed along the way, and why, without repeats. */
export function changeNotes(payload: ConceptsPayload): string[] {
  return [...new Set(list(payload.notes).map((note) => note.trim()))];
}

/** Up to this many notes show as they are; a longer list folds away behind its count. */
export const NOTES_SHOWN = 3;

/** The rules the server read from the owner's notes, as the section names them: "No alcohol", "Budget prices". */
export function ruleNames(understood: readonly string[]): string[] {
  const names = understood.map((rule) => rule.trim()).filter(Boolean);
  return [...new Set(names.map((rule) => rule.charAt(0).toUpperCase() + rule.slice(1)))];
}

/** The standfirst's last sentences when there is a wild card: what it is, by its kind, and why it is not ranked. */
function wildNote(concepts: readonly Concept[]): string {
  const wild = concepts.find(isWildcard);
  if (!wild) return "";
  const what = themeOf(wild)
    ? "a kind of place people here love, built around a theme from what they watch, hear and follow"
    : "two things people here love, combined";
  return ` The last is a wild card: ${what}. It is untested, so it is not ranked.`;
}

/** The section's standfirst: who designed the concepts and, when there is one, what the wild card is. */
export function conceptsNote({ mode, model, note, concepts }: ConceptsPayload): string {
  const wild = wildNote(concepts ?? []);
  if (mode === "agent") {
    return `Designed by ${agentCredit(model)} from the gaps the survey found. Every claim traces back to Qloo evidence.${wild}`;
  }
  if (mode === "rules") return `Built from the evidence by deterministic rules (no AI model was available).${wild}`;
  return note ?? "";
}
