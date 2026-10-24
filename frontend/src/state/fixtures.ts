/* Test data: one explore survey as its stream sent it, and copies of its record as the server would return them; the
   area and age focus of features/CONTRACT.md as the server sends them; and the finished examples of
   features/EXAMPLES.md as GET /api/examples lists them. */
import type {
  Example,
  GapRow,
  RecordedEvent,
  RunRecord,
  RunSite,
  RunStatus,
  StepState,
  SurveyEvent,
  Walk,
} from "../api/types";

export function status(step: string, state: StepState, label = `Step ${step}`): SurveyEvent {
  return { event: "status", data: { step, state, label } };
}

export function gap(genre: string, score: number, extra: Partial<GapRow> = {}): GapRow {
  return {
    genre_id: `urn:tag:genre:place:${genre.toLowerCase().replace(/ /g, "_")}`,
    genre,
    demand_rank: 2,
    ref_rank: 6,
    nearby_count: 2,
    nearby_capped: false,
    favorites_kind: "local",
    favorites_total: 5,
    favorites_far: 4,
    median_favorite_km: 2.4,
    expected_nearby: 3.5,
    lift: 0.4,
    relative_supply: 0.7,
    leakage: 0.71,
    evidence: "ok",
    gap_score: score,
    ...extra,
  };
}

export const SITE: RunSite = {
  lat: 30.2622,
  lon: -97.7247,
  label: "East Austin, Texas",
  focus: "food_drink",
  notes: "no alcohol",
  minutes: 10,
  size_m2: 60,
  kitchen: "light",
  outdoor: false,
  intent: "explore",
  business: "",
  place_id: "",
};

export const RUN_EVENT: SurveyEvent = { event: "run", data: { run_id: "r1", llm: true, understood: ["no alcohol"], site: SITE } };
export const DONE_EVENT: SurveyEvent = { event: "done", data: { run_id: "r1", seconds: 21.6, qloo_calls: 57, cache_hits: 3 } };

/** A 30-minute drive from a suburb, for people aged 25–34, as the brief asks for it and the server records it. */
export const DRIVE_SITE: RunSite = {
  ...SITE,
  lat: 30.5083,
  lon: -97.6789,
  label: "Round Rock, Texas",
  travel: "drive",
  minutes: 30,
  km: null,
  ages: "25_34",
};

/** The drive as the server traces it, with its own words. */
export const DRIVE_WALK: Walk = {
  minutes: 30,
  source: "street network",
  ring: [
    [30.42, -97.76],
    [30.6, -97.6],
  ],
  area_km2: 210.37,
  radius_m: 9200,
  travel: "drive",
  km: null,
  label: "30-minute drive",
  short: "30-min drive",
};

export const DRIVE_RUN_EVENT: SurveyEvent = {
  event: "run",
  data: { run_id: "r2", llm: true, understood: [], site: DRIVE_SITE, area_label: "30-minute drive", ages_label: "25–34" },
};

/** A road distance off the quick picks: 12.5 km of road, for everyone. `minutes` is the brief's walk, unused. */
export const DISTANCE_SITE: RunSite = { ...SITE, travel: "distance", km: 12.5, minutes: 10, ages: "all" };

const WALK = "Tracing a 10-minute walk over the street network";
const BLOCK = "Reading every place inside the 10-minute walk";

/** The survey's events with their times, in the order the stream sent them; the baseline arrives after "done". */
export const TIMELINE: [SurveyEvent, number][] = [
  [RUN_EVENT, 0.01],
  [status("walk", "running", WALK), 0.02],
  [
    {
      event: "catchment",
      data: { minutes: 10, source: "street network", ring: [[30.26, -97.73], [30.27, -97.72]], area_km2: 1.21, radius_m: 640 },
    },
    1.4,
  ],
  [status("walk", "done", WALK), 1.41],
  [status("block", "running", BLOCK), 1.42],
  [{ event: "block", data: { summary: { place_count: 95, top_genres: [["Cafe", 12]] }, places: [] } }, 4.8],
  [status("block", "done", BLOCK), 4.81],
  [{ event: "demand", data: { cues: ["Jazz"] } }, 4.9],
  [status("gaps", "running", "Comparing supply"), 5.1],
  [status("gaps", "done", "Comparing supply"), 8.2],
  [{ event: "gaps", data: { rows: [gap("Seafood", 67), gap("Wine Bar", 41)] } }, 8.21],
  [{ event: "agent", data: { tool: "inspect_gap", args: { genre: "Seafood", reason: "Strongest gap" } } }, 9],
  [{ event: "finding", data: { text: "Locals travel 2.4 km for seafood" } }, 12.5],
  [{ event: "concepts", data: { concepts: [{ name: "Tidewater", genre: "Seafood", gap_score: 67 }], mode: "agent" } }, 21.5],
  [DONE_EVENT, 21.6],
  [{ event: "baseline", data: { concepts: [{ name: "Coffee shop", genre: "Cafe" }] } }, 23],
];

const recorded = ([event, t]: [SurveyEvent, number]): RecordedEvent => [event.event, event.data, t];

/** The record's events: the timeline, plus an event this app does not know, which the server records all the same. */
export const RAW: RecordedEvent[] = [
  ...TIMELINE.slice(0, 8).map(recorded),
  ["crowd", { share: 0.4 }, 5],
  ...TIMELINE.slice(8).map(recorded),
];

/** The record as the server returns it with its first `count` events. */
export function recordOf(state: RunStatus, count = RAW.length): RunRecord {
  return { id: "r1", status: state, created_at: "2026-10-22T14:00:00Z", events: RAW.slice(0, count) };
}

/** A record of another timeline. */
export function recordFrom(state: RunStatus, timeline: [SurveyEvent, number][]): RunRecord {
  return { id: "r1", status: state, created_at: "2026-10-22T14:00:00Z", events: timeline.map(recorded) };
}

const KIT_TOKEN = "Uv6RpsfnBAa0kIfOdIEEVukHMeS9bqXG1imQEaiFuj4";

/** The local examples as GET /api/examples lists them: a drive with a ready kit, a walk for 25–34, and an idea tested. */
export const EXAMPLE_DRIVE: Example = {
  run_id: "b21ec69b0e92",
  url: "/s/b21ec69b0e92",
  label: "Zamalek, Cairo",
  intent: "explore",
  business: null,
  area: "10 km drive",
  ages: null,
  llm: true,
  headline: "Smash & Shroom",
  verdict: null,
  concepts: ["Smash & Shroom", "Aura Brew & Press", "Willow Table"],
  gaps: 8,
  top_gaps: ["Personal care", "Hamburger restaurant", "Coffee shop"],
  kit: { token: KIT_TOKEN, index: 0, name: "Smash & Shroom", url: `/k/${KIT_TOKEN}`, report_url: `/k/${KIT_TOKEN}/dossier` },
};

export const EXAMPLE_AGES: Example = {
  run_id: "d2aa4df573aa",
  url: "/s/d2aa4df573aa",
  label: "Upper East Side, Manhattan",
  intent: "explore",
  business: null,
  area: "10-minute walk",
  ages: "25–34",
  llm: true,
  headline: "The Amplified Parlor",
  verdict: null,
  concepts: ["The Amplified Parlor", "Sake & Sound Lounge", "Poppy Taproom", "Encore & Elegy"],
  gaps: 8,
  top_gaps: ["Live music venue", "Lounge", "Personal care"],
  kit: null,
};

export const EXAMPLE_IDEA: Example = {
  run_id: "82e186998efa",
  url: "/s/82e186998efa",
  label: "Upper East Side, Manhattan",
  intent: "open",
  business: "Starbucks",
  area: "10-minute walk",
  ages: null,
  llm: true,
  headline: "Eastside Reserve Roasters",
  verdict:
    "Coffee Shop is a weak gap here (#9 of 9): demand and supply here are close to what the areas around show.",
  concepts: ["Eastside Reserve Roasters", "Eastside Market Table", "Madison & Dusk", "Tide & Spirit"],
  gaps: 8,
  top_gaps: ["New American", "Lounge", "Brunch"],
  kit: null,
};

export const EXAMPLES: Example[] = [EXAMPLE_DRIVE, EXAMPLE_AGES, EXAMPLE_IDEA];
