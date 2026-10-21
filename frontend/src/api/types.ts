/* Payloads of the Blank Space API (app/main.py), limited to the fields this app reads. */

export type Focus = "any" | "food_drink" | "retail" | "leisure";
export type WalkMinutes = 5 | 10 | 15;
export type LatLon = [number, number];

export interface Preset {
  id: string;
  label: string;
  lat: number;
  lon: number;
  blurb: string;
}

export interface GeocodeResult {
  label: string | null;
  lat: number;
  lon: number;
}

export interface Walk {
  minutes: number;
  source: string;
  ring: LatLon[];
  area_km2: number;
  radius_m: number;
}

export interface PlaceCard {
  name: string | null;
  rating?: number | null;
  price_level?: number | null;
  genres?: string[];
  praise?: string[];
  complaints?: string[];
  lat: number | null;
  lon: number | null;
  distance_m?: number;
}

export interface FavoritePlace extends PlaceCard {
  within_walk?: boolean;
}

/** A name and how often it occurs: a genre and its places, or a review keyword and its mentions. */
export type Tally = [string, number];

export interface BlockSummary {
  place_count?: number;
  top_genres?: Tally[];
  avg_rating?: number | null;
  price_levels?: Record<string, number>;
  praise?: Tally[];
  complaints?: Tally[];
}

export interface BlockPayload {
  summary: BlockSummary;
  places: PlaceCard[];
}

export interface DemandPayload {
  cues?: string[];
}

export type Evidence = "ok" | "thin" | "atypical";

export interface GapRow {
  genre_id: string;
  genre: string;
  demand_rank: number;
  ref_rank: number | null;
  nearby_count: number;
  nearby_capped: boolean;
  favorites_kind: "local" | "citywide";
  favorites_total: number;
  favorites_far: number;
  median_favorite_km: number | null;
  expected_nearby?: number | null;
  lift: number;
  relative_supply: number;
  leakage: number | null;
  evidence: Evidence;
  gap_score: number;
  competitors?: PlaceCard[];
  favorites?: FavoritePlace[];
  source?: string;
}

export interface HeatCell {
  lat: number;
  lon: number;
  geohash: string | null;
  affinity: number;
}

export interface TasteEntity {
  name: string | null;
  image?: string | null;
}

export interface TastePayload {
  brands?: TasteEntity[];
  distinctive_brands?: TasteEntity[];
  artists?: TasteEntity[];
  distinctive_artists?: TasteEntity[];
}

/** Lists written by the agent are cleaned by the server but not guaranteed to be lists, hence `unknown`. */
export interface Concept {
  name: string;
  genre: string;
  gap_score: number;
  one_liner?: string;
  price_level?: number;
  why_here?: unknown;
  signature?: unknown;
  inspired_by?: unknown;
  risk?: string;
}

export interface ConceptsPayload {
  concepts?: Concept[];
  mode?: string;
  note?: string;
  model?: string | null;
  replayed_from?: number | null;
}

export interface BaselineConcept {
  name?: string;
  genre?: string;
}

export interface RunPayload {
  run_id: string;
  llm: boolean;
}

export type StepState = "running" | "done" | "failed";

export interface StatusPayload {
  step: string;
  state: StepState;
  label: string;
}

export interface AgentPayload {
  tool: string;
  args?: Record<string, unknown> | null;
}

export interface ReplayPayload {
  saved_at?: number | null;
  model?: string | null;
}

export interface DonePayload {
  run_id: string;
  seconds: number;
  qloo_calls: number;
  cache_hits: number;
}

export type SurveyEvent =
  | { event: "run"; data: RunPayload }
  | { event: "status"; data: StatusPayload }
  | { event: "catchment"; data: Walk }
  | { event: "agent"; data: AgentPayload }
  | { event: "replay"; data: ReplayPayload }
  | { event: "finding"; data: { text: string } }
  | { event: "explored"; data: { row?: GapRow | null } }
  | { event: "block"; data: BlockPayload }
  | { event: "demand"; data: DemandPayload }
  | { event: "gaps"; data: { rows?: GapRow[] } }
  | { event: "taste"; data: TastePayload }
  | { event: "concepts"; data: ConceptsPayload }
  | { event: "baseline"; data: { concepts?: BaselineConcept[] } }
  | { event: "notice"; data: { message: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: DonePayload };

export interface RunRequest {
  lat: number;
  lon: number;
  label: string;
  focus: Focus;
  notes: string;
  minutes: WalkMinutes;
}

export interface Interior {
  mood?: string;
  materials?: unknown;
  lighting?: string;
  layout?: string;
  seating?: string;
}

export interface Partner {
  name?: string;
  why?: string;
}

export interface Design {
  name?: string;
  tagline?: string;
  concept_statement?: string;
  interior?: Interior | null;
  offer?: unknown;
  price_level?: number;
  hours?: string;
  music?: { direction?: string; artists?: unknown } | null;
  partners?: Partner[] | null;
  dna?: Record<string, unknown> | null;
  mode?: string;
  model?: string | null;
  shots?: unknown;
  renders?: { enabled?: boolean; model?: string | null } | null;
}

export interface Shot {
  kind: string;
  label: string;
}

export interface RenderResult {
  image?: string | null;
  model?: string | null;
  queued?: boolean;
  detail?: string;
}
