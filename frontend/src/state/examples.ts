/* The finished example surveys anyone can open before running one (features/EXAMPLES.md): read once per page load,
   for the examples page, the first screen's strip, the header's link, the line shown while a survey runs and the
   banner on an example's pages. Nothing waits on them: until they arrive, and when there are none, those show nothing. */
import { useEffect, useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { Example } from "../api/types";

export interface ExamplesState {
  /** "loading" until the one request has answered, or failed. */
  phase: "loading" | "ready";
  /** In the server's order; empty when none is configured or the request failed. */
  list: readonly Example[];
}

export interface ExamplesStore {
  get: () => ExamplesState;
  subscribe: (listener: () => void) => () => void;
  /** Asks the server once; later calls share that answer. */
  load: () => Promise<void>;
}

export const INITIAL_EXAMPLES: ExamplesState = { phase: "loading", list: [] };

const text = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const texts = (value: unknown): string[] => (Array.isArray(value) ? value.filter(text) : []);

/** An example the screens can show and open: it has its survey's id, address and site. */
function usable(value: unknown): value is Partial<Example> & Pick<Example, "run_id" | "url" | "label"> {
  if (typeof value !== "object" || value === null) return false;
  const example = value as Partial<Example>;
  return text(example.run_id) && text(example.url) && text(example.label);
}

/** The server's answer as a list of examples the screens can open, their lists and counts made safe to read. */
export function readExamples(body: unknown): Example[] {
  if (!Array.isArray(body)) return [];
  return body.filter(usable).map((example) => ({
    ...example,
    intent: text(example.intent) ? example.intent : "explore",
    area: text(example.area) ? example.area : "",
    llm: example.llm === true,
    concepts: texts(example.concepts),
    gaps: typeof example.gaps === "number" && Number.isFinite(example.gaps) ? example.gaps : 0,
    top_gaps: texts(example.top_gaps),
    kit: example.kit && text(example.kit.token) && text(example.kit.url) && text(example.kit.report_url) ? example.kit : null,
  }));
}

export function createExamplesStore(fetchExamples: () => Promise<unknown>): ExamplesStore {
  let state = INITIAL_EXAMPLES;
  let loading: Promise<void> | null = null;
  const listeners = new Set<() => void>();

  function load(): Promise<void> {
    loading ??= fetchExamples().then(
      (body) => {
        state = { phase: "ready", list: readExamples(body) };
        for (const listener of listeners) listener();
      },
      () => {
        state = { phase: "ready", list: [] };
        for (const listener of listeners) listener();
      },
    );
    return loading;
  }

  return {
    get: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load,
  };
}

export const examples = createExamplesStore(() => api.examples());

/** The examples, asked for on first use; an empty list meanwhile, and for good when the request fails. */
export function useExamples(): ExamplesState {
  const state = useSyncExternalStore(examples.subscribe, examples.get);
  useEffect(() => {
    void examples.load();
  }, []);
  return state;
}

/** The example a survey's id belongs to, or null. */
export function surveyExample(list: readonly Example[], runId: string | null | undefined): Example | null {
  return runId ? (list.find((example) => example.run_id === runId) ?? null) : null;
}

/** The example whose launch kit has this token (its kit's page and its report), or null. */
export function kitExample(list: readonly Example[], token: string | null | undefined): Example | null {
  return token ? (list.find((example) => example.kit?.token === token) ?? null) : null;
}

/** "For 25–34" when the survey served an age group; null when it served everyone. */
export function exampleWho(example: Example): string | null {
  return text(example.ages) ? `For ${example.ages}` : null;
}

/** "Testing: Starbucks" for a survey that tested the owner's idea; null otherwise. */
export function exampleTesting(example: Example): string | null {
  return example.intent === "open" && text(example.business) ? `Testing: ${example.business}` : null;
}

/** The facts a card sets under the site: the area, the age group, and the idea tested. */
export function exampleTags(example: Example): string[] {
  return [example.area, exampleWho(example), exampleTesting(example)].filter(text);
}

/** The area as chips say it ("10-min walk", "30-min drive", "25 km drive"), for the small cards of the first screen. */
export function shortArea(area: string): string {
  return area.replace(/^(\d+)-minute (walk|drive)$/, "$1-min $2");
}

/** The first screen's small cards: the area as chips say it, the age group, the idea tested. */
export function exampleChips(example: Example): string[] {
  return [shortArea(example.area), exampleWho(example), exampleTesting(example)].filter(text);
}

/** "8 categories ranked · most missing: Personal care, Hamburger restaurant, Coffee shop". */
export function exampleFound(example: Example): string {
  const ranked = `${example.gaps} ${example.gaps === 1 ? "category" : "categories"} ranked`;
  return example.top_gaps.length ? `${ranked} · most missing: ${example.top_gaps.join(", ")}` : ranked;
}

/** The concept the survey leads with, or its top gap; null when it has neither. */
export function exampleLead(example: Example): string | null {
  return [example.headline, example.concepts[0], example.top_gaps[0]].find(text) ?? null;
}
