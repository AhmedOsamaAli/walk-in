/* The design sheet's readings (DesignContent.tsx, and the report's room): the unit in words, and the offer with what
   the concept's own evidence says about each item. Pure, so they are tested without a browser. */
import type { Concept, Design, UnitText } from "../api/types";
import { list } from "./format";

/** "60 m² (646 ft²), a light-prep kitchen, no outdoor space": only what the owner said. */
export function unitText(unit: UnitText | null | undefined): string | null {
  if (!unit) return null;
  const outdoor = unit.outdoor_space === "yes" ? "outdoor space" : unit.outdoor_space === "none" ? "no outdoor space" : null;
  const parts = [unit.size, unit.kitchen].filter((part) => part && part !== "unknown");
  if (outdoor) parts.push(outdoor);
  return parts.length ? parts.join(", ") : null;
}

/**
 * "new": the places people here love of this kind are known for it, and none inside the walk is.
 * "loved": the places people here love of this kind are known for it.
 * null: the concept's own pick, which the evidence says nothing about.
 */
export type OfferMark = "new" | "loved" | null;

export interface OfferItem {
  item: string;
  mark: OfferMark;
}

const plain = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");
const key = (text: string) => plain(text).toLowerCase();

/** The list after "…known for and none inside the 10-minute walk is:" in the concept's competition line, which the
 * server writes from the evidence for every concept, the agent's too. Older lines say "inside the walk"; drives and
 * distances name their area. */
function newClause(concept: Concept): string | null {
  const said = /known for and none inside the .+? is: (.+?)\.?$/i.exec(plain(concept.beat_competitors ?? ""));
  return said?.[1] ? said[1].toLowerCase() : null;
}

/**
 * The items a list written "a, b and c" names. An item may hold an "and" itself ("fish and chips"), so the last part is
 * read the way that makes every piece an item of the offer, and claims nothing when no reading does.
 */
function namedIn(clause: string, offered: Set<string>): Set<string> {
  const parts = clause.split(", ");
  const last = parts.pop() ?? "";
  const words = last.split(" and ");
  // After a comma the last part is two items; without one it may be a single item too.
  const readings = parts.length ? [] : [[last]];
  for (let cut = 1; cut < words.length; cut += 1) {
    readings.push([words.slice(0, cut).join(" and "), words.slice(cut).join(" and ")]);
  }
  const reading = readings.find((pieces) => pieces.every((piece) => offered.has(piece))) ?? [];
  return new Set([...parts, ...reading]);
}

/**
 * The sheet's offer, each item marked where the concept's evidence says so. The server writes the concept's signature
 * first and then what the places people here love of this kind are known for, so on a sheet the evidence rules made,
 * every item past the signature is one those places are known for. An item is new to the block only where the
 * concept's competition line, or a "new" claim of its launch plan, says none inside the walk is known for it.
 */
export function offerItems(design: Design, concept: Concept): OfferItem[] {
  const items = new Map<string, string>();
  for (const raw of list(design.offer)) if (!items.has(key(raw))) items.set(key(raw), plain(raw));
  const signature = new Set(list(concept.signature).map(key));
  const clause = newClause(concept);
  const named = clause ? namedIn(clause, new Set(items.keys())) : new Set<string>();
  const claimed = (design.launch?.claims ?? []).filter((claim) => claim.kind === "new").map((claim) => key(claim.line));
  return [...items].map(([lower, item]) => {
    const isNew = named.has(lower) || claimed.some((line) => line.startsWith(`${lower}, which no `));
    const loved = design.mode !== "agent" && !signature.has(lower);
    return { item, mark: isNew ? "new" : loved ? "loved" : null };
  });
}
