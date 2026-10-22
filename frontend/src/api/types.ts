/* Payloads of the Blank Space API (app/main.py), limited to the fields this app reads. */

export type Focus = "any" | "food_drink" | "retail" | "leisure";
export type WalkMinutes = 5 | 10 | 15;
export type LatLon = [number, number];
/** What the owner wants: the block's best businesses, a verdict on their own idea, or how to improve their place. */
export type Intent = "explore" | "open" | "improve";
export type Kitchen = "full" | "light" | "none";

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

/** A place on Qloo near the pin, found by name (GET /api/places), for "improve my place". */
export interface PlaceHit {
  id: string;
  name: string;
  address?: string | null;
  genres?: string[];
  rating?: number | null;
  lat: number;
  lon: number;
  distance_m?: number | null;
}

export interface Walk {
  minutes: number;
  source: string;
  ring: LatLon[];
  area_km2: number;
  radius_m: number;
}

/** Why a place counts as established: a Michelin Guide listing or a long TripAdvisor review history. */
export interface Standing {
  reviews: number | null;
  /** "listed", "1 star", "2 stars"... */
  michelin?: string;
}

export interface PlaceCard {
  id?: string | null;
  name: string | null;
  address?: string | null;
  image?: string | null;
  /** Its menu page when Qloo has one, else its website: where its real prices can be checked. */
  url?: string | null;
  link?: "menu" | "site" | null;
  rating?: number | null;
  price_level?: number | null;
  genres?: string[];
  /** The dishes and experience themes its reviews mention most, written to read inside a sentence. */
  known_for?: string[];
  /** Complaint themes from its reviews, written the same way. */
  complaints?: string[];
  standing?: Standing | null;
  lat: number | null;
  lon: number | null;
  distance_m?: number;
}

export interface FavoritePlace extends PlaceCard {
  within_walk?: boolean;
}

/** A name and how often it occurs: a place type and its places. */
export type Tally = [string, number];

/** Review keywords that mean the same thing, grouped: a dish, an experience theme or a complaint theme. */
export interface TopicGroup {
  label: string;
  mentions: number;
  /** How many places' reviews mention it. */
  places: number;
  /** The keywords as reviews write them, most mentioned first. */
  keywords: string[];
}

/** An established favorite inside the walk. */
export interface Classic extends Standing {
  id: string | null;
  name: string;
  genre: string;
  price_level?: number | null;
  known_for: string[];
}

export interface BlockSummary {
  place_count?: number;
  top_genres?: Tally[];
  avg_rating?: number | null;
  price_levels?: Record<string, number>;
  menu?: TopicGroup[];
  experience?: TopicGroup[];
  complaints?: TopicGroup[];
  classics?: Classic[];
}

export interface BlockPayload {
  summary: BlockSummary;
  places: PlaceCard[];
}

export interface DemandPayload {
  cues?: string[];
}

export type Evidence = "ok" | "thin" | "atypical";

/** A real place at a price level, whose own menu or website shows what that level costs here. */
export interface PriceAnchor {
  name: string;
  level: number;
  url: string | null;
  link: "menu" | "site" | null;
  within_walk: boolean;
}

/** One of Qloo's four price levels: how many places locals love, and how many inside the walk, sit there. */
export interface PriceStep {
  level: number;
  loved: number;
  inside: number;
}

export interface PriceEvidence {
  /** The level to charge: what the evidence supports, within the owner's price range. */
  level: number | null;
  evidence_level: number | null;
  /** Median price level of the places locals love, and of the places inside the walk. */
  loved: number | null;
  nearby: number | null;
  basis: string;
  ladder?: PriceStep[];
  /** "No $$$ cocktail bar inside the walk, while 3 of the 8 cocktail bars locals love are $$$: that price level is open." */
  open_note?: string | null;
  anchors?: PriceAnchor[];
}

export interface UnitFit {
  fits: boolean;
  reason: string | null;
  /** The kitchen the category needs. */
  needs?: Kitchen;
  capacity_text?: string | null;
}

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
  /** The row in two or three words ("Clear gap", "Crowded"), and in plain sentences with its numbers. */
  reading?: string;
  why?: string[];
  price?: PriceEvidence;
  fit?: UnitFit | null;
  /** Why the owner's notes rule the category out ("serves alcohol"), or null. */
  ruled_out?: string | null;
}

export interface HeatCell {
  lat: number;
  lon: number;
  geohash: string | null;
  affinity: number;
}

export interface TasteEntity {
  id?: string | null;
  name: string | null;
  image?: string | null;
  /** Release year of a film or show. */
  year?: number | null;
  /** The year an artist started. */
  since?: number | null;
}

export interface TastePayload {
  brands?: TasteEntity[];
  distinctive_brands?: TasteEntity[];
  artists?: TasteEntity[];
  distinctive_artists?: TasteEntity[];
  distinctive_movies?: TasteEntity[];
  distinctive_tv?: TasteEntity[];
  distinctive_podcasts?: TasteEntity[];
}

/** One item of an experience plan: an artist to play, a film or show to screen, a podcast to host. */
export interface ExperienceCard extends TasteEntity {
  /** "classic" for an established artist or an older title, "new" for a recent one. */
  era?: "classic" | "new";
}

/** What to play, screen and host, from what people within 1.5 km over-index on. */
export interface ExperiencePlan {
  soundtrack?: ExperienceCard[];
  screen?: ExperienceCard[];
  talks?: ExperienceCard[];
  basis?: string;
  licensing?: string | null;
}

export type VerdictLevel = "strong" | "possible" | "weak" | "thin" | "misfit" | "unknown";

/** How the business the owner wants to open ranks among the site's gaps. */
export interface Verdict {
  query: string;
  found: boolean;
  genre?: string;
  level: VerdictLevel;
  headline: string;
  position?: number;
  of?: number;
  gap_score?: number;
  evidence: string[];
  row?: GapRow;
}

/** What the place and the places locals love in its category have; `missing` counts the places that offer it. */
export interface OfferDiff {
  missing: { name: string; places: number }[];
  shared: string[];
  own: string[];
}

export interface Comparison {
  peers: number;
  /** "places locals love" or "places locals love at a similar price". */
  peers_label: string;
  /** False when few peers are priced like the place, so their offer and hours are a weak guide. */
  comparable: boolean;
  peer_names: string[];
  /** The peers' own menus or websites, where their real prices can be checked. */
  peer_links?: { name: string; price_level: number | null; url: string | null; link: "menu" | "site" | null }[];
  rating: { place: number | null; peers: number | null };
  price: { place: number | null; peers: number | null };
  hours: { place: Record<string, string> | null; peers: Record<string, string> | null };
  offer: Record<string, OfferDiff>;
  known_for: string[];
  /** The complaint themes in the place's own reviews. */
  complaints: TopicGroup[];
  peers_known_for: string[];
  standing?: Standing | null;
}

export interface Move {
  title: string;
  why: string;
}

/** The owner's place against the places locals love in its category. */
export interface Improvement {
  place: PlaceCard;
  genre: string;
  comparison: Comparison;
  moves: Move[];
  experience: ExperiencePlan | null;
  row?: GapRow;
}

export type ImprovePayload = Improvement | { note: string };

export interface PlacePayload {
  place: PlaceCard;
  site: { lat: number; lon: number; label: string };
}

/** Lists written by the agent are cleaned by the server but not guaranteed to be lists, hence `unknown`. */
export interface Concept {
  name: string;
  genre: string;
  gap_score: number;
  one_liner?: string;
  for_whom?: string;
  /** Null when Qloo lists no prices for the category here. */
  price_level?: number | null;
  price_basis?: string;
  price_anchors?: PriceAnchor[];
  why_here?: unknown;
  beat_competitors?: string;
  signature?: unknown;
  inspired_by?: unknown;
  risk?: string;
}

export interface ConceptsPayload {
  concepts?: Concept[];
  mode?: string;
  note?: string;
  /** A plain warning when even the best concept rests on a weak gap. */
  caution?: string;
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
  /** What the server read from the owner's notes as rules ("no alcohol", "budget prices ($–$$)"). */
  understood?: string[];
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
  | { event: "place"; data: PlacePayload }
  | { event: "catchment"; data: Walk }
  | { event: "agent"; data: AgentPayload }
  | { event: "replay"; data: ReplayPayload }
  | { event: "finding"; data: { text: string } }
  | { event: "explored"; data: { row?: GapRow | null } }
  | { event: "block"; data: BlockPayload }
  | { event: "demand"; data: DemandPayload }
  | { event: "gaps"; data: { rows?: GapRow[] } }
  | { event: "taste"; data: TastePayload }
  | { event: "verdict"; data: Verdict }
  | { event: "improve"; data: ImprovePayload }
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
  intent: Intent;
  /** The business to open (intent "open"). */
  business?: string;
  /** The owner's place on Qloo (intent "improve"). */
  placeId?: string;
  sizeM2?: number;
  kitchen?: Kitchen;
  outdoor?: boolean;
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
  price_level?: number | null;
  price_basis?: string;
  price_anchors?: PriceAnchor[];
  hours?: string | null;
  hours_basis?: string | null;
  /** "about 27–32 seated guests at most", when the owner gave the unit's size. */
  capacity?: string | null;
  capacity_basis?: string | null;
  unit?: { size: string; kitchen: string; outdoor_space: string } | null;
  experience?: ExperiencePlan | null;
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
