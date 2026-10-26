/* Payloads of the Walk-in API (app/schemas.py and app/routes/), limited to the fields this app reads. */

export type Focus = "any" | "food_drink" | "retail" | "leisure";
export type LatLon = [number, number];
/** What the owner wants: the block's best businesses, a verdict on their own idea, or how to improve their place. */
export type Intent = "explore" | "open" | "improve";
export type Kitchen = "full" | "light" | "none";
/** How the survey area is measured: a walk or a drive of `minutes`, or a road distance of `km`. */
export type Travel = "walk" | "drive" | "distance";
/** Who the owner wants to serve; "all" leaves Qloo's ranking unbiased. */
export type Ages = "all" | "under_25" | "25_34" | "35_54" | "55_plus";

export interface Preset {
  id: string;
  label: string;
  lat: number;
  lon: number;
  blurb: string;
}

/** A finished example survey's launch kit (GET /api/examples). */
export interface ExampleKit {
  token: string;
  /** The concept the kit was made for. */
  index: number;
  name?: string | null;
  /** "/k/{token}" */
  url: string;
  /** "/k/{token}/dossier", the printable report. */
  report_url: string;
}

/**
 * A finished survey anyone can open before running their own (GET /api/examples). It replays what was
 * saved, so opening it spends no Qloo or AI quota.
 */
export interface Example {
  run_id: string;
  /** "/s/{run_id}" */
  url: string;
  /** The site, as the survey named it: "Zamalek, Cairo". */
  label: string;
  intent: string;
  /** The business tested, for intent "open". */
  business?: string | null;
  /** "10-minute walk", "30-minute drive", "25 km drive". */
  area: string;
  /** "25–34"; null for everyone. */
  ages?: string | null;
  /** Whether the concepts were written with the AI agent. */
  llm: boolean;
  /** The top concept's name, or the top gap. */
  headline?: string | null;
  /** The verdict's headline, for intent "open". */
  verdict?: string | null;
  concepts: string[];
  /** Categories ranked. */
  gaps: number;
  top_gaps: string[];
  /** The first concept with a ready launch kit; null when none is built. */
  kit?: ExampleKit | null;
}

export interface GeocodeResult {
  label: string | null;
  lat: number;
  lon: number;
}

/** The address of a pin dropped on the map (GET /api/reverse; 404 when the point has none). */
export interface ReverseResult {
  /** The street address and the two smallest parts of town: "131 South 2nd Street, Williamsburg, Brooklyn". */
  label: string;
  /** OpenStreetMap's full address line. */
  address: string;
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
  /** Missing on surveys made before drives and distances: a walk. */
  travel?: Travel;
  /** Road distance in km, for travel "distance". */
  km?: number | null;
  /** "10-minute walk", "30-minute drive", "25 km drive": say this in sentences, never compose "N-minute walk". */
  label?: string;
  /** "10-min walk", "30-min drive", "25 km drive": for chips and the map line. */
  short?: string;
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
  /** Its menu page when Qloo has one, else its website: where its offer can be checked. */
  url?: string | null;
  link?: "menu" | "site" | null;
  rating?: number | null;
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
  known_for: string[];
}

export interface BlockSummary {
  place_count?: number;
  top_genres?: Tally[];
  avg_rating?: number | null;
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

/** A place of the gap's kind that OpenStreetMap shows inside the walk and Qloo does not list there. */
export interface OsmPlace {
  name: string;
  lat: number;
  lon: number;
  /** Its OpenStreetMap page, such as https://www.openstreetmap.org/node/123. */
  url: string;
  /** What OpenStreetMap says it is: "shop=bakery". */
  tag?: string | null;
  distance_m?: number;
}

/** The gap's cross-check with OpenStreetMap. Its data is © OpenStreetMap contributors, under the ODbL. */
export interface OsmCheck {
  /** False when OpenStreetMap did not answer, or no tag reliably marks this kind of place. */
  checked: boolean;
  /** Places of this kind OpenStreetMap shows inside the walk, Qloo's included. */
  count: number;
  /** The ones Qloo does not list there, nearest first; the gap counts them as supply. */
  extra: OsmPlace[];
  reason?: "unavailable" | "unmapped" | "off" | "too_big" | null;
  /** The reason in words, or why the places were counted but not compared one by one. */
  note?: string | null;
  /** When the OpenStreetMap data was last updated on the server that answered. */
  as_of?: string | null;
  credit?: string | null;
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
  /** Places of this kind Qloo lists inside the walk; `osm.extra` holds those only OpenStreetMap shows. */
  nearby_count: number;
  nearby_capped: boolean;
  favorites_kind: "local" | "citywide";
  favorites_total: number;
  favorites_far: number;
  median_favorite_km: number | null;
  /** The median trip to the favorites outside the area (app/scoring.py); absent on rows saved before it existed. */
  median_far_km?: number | null;
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
  fit?: UnitFit | null;
  /** Why the owner's notes rule the category out ("serves alcohol"), or null. */
  ruled_out?: string | null;
  /** The OpenStreetMap cross-check; missing in surveys saved before it existed. */
  osm?: OsmCheck | null;
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
  /** The brand's own stores in the area, when the business named is a chain Qloo knows. */
  chain?: ChainCheck | null;
}

/** How many stores of a chain are already in the area ("Test my idea" with a brand name). */
export interface ChainCheck {
  brand: string;
  inside: number;
  /** Stores in the area twice as far; null when it could not be counted. */
  around: number | null;
  /** True when `inside` hit the counting limit: show it as "50+". */
  capped?: boolean;
  /** Ready to show: "1 Starbucks is already inside the 10-minute walk, and 4 within a 20-minute walk." */
  line: string;
  basis: string;
}

/**
 * Who the places people here love draw, from Qloo's audience data: relative leans against everyone,
 * not head counts.
 */
export interface Audience {
  /** The age band these places lean to most clearly, "35–44"; null when no band stands out. */
  ages: string | null;
  age_min: number | null;
  age_max: number | null;
  /** Only when the lean is clear. */
  gender: "women" | "men" | null;
  /** Six rows in order (Under 25, 25–29, 30–34, 35–44, 45–54, 55+), lean from -1 to 1 where 0 is like everyone. */
  bands: { band: string; lean: number }[];
  /** Above 0 leans women, below 0 leans men; null when unknown. */
  gender_lean: number | null;
  /** The loved places it is read from. */
  places: string[];
  line: string;
  basis: string;
  /** What an ad platform takes: "Ages 30–44, women"; null when nothing leans clearly. */
  ad?: string | null;
  /** True when too few loved places had audience data, so this is the category everywhere (the line says so). */
  general?: boolean;
  /**
   * Who the places of this kind already inside the area draw, read the same way (median leans);
   * null when fewer than 3 of them have audience data, or the audience is `general`.
   */
  inside?: {
    ages: string | null;
    gender: "women" | "men" | null;
    gender_lean: number | null;
    bands: { band: string; lean: number }[];
    places: string[];
  } | null;
  /**
   * Ready to show, only when the places already here lean away from a group the loved places draw:
   * "The 6 hamburger places already inside the walk … The ones people here love draw women: aim the concept at them."
   */
  tip?: string | null;
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
  /** The peers' own menus or websites, where their offer can be checked. */
  peer_links?: { name: string; url: string | null; link: "menu" | "site" | null }[];
  rating: { place: number | null; peers: number | null };
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

/** One of the two things a wild-card concept combines, and the Qloo evidence that people here love it. */
export interface LoveItem {
  /** What people here love, in plain words: "coffee shops". */
  item: string;
  /** Its category in the gap table. */
  genre: string;
  /** The evidence in words: the trips people here make for it, or how they rank it. */
  source: string;
}

/**
 * Lists written by the agent are cleaned by the server but not guaranteed to be lists, hence `unknown`. The ranked
 * concepts come first, then at most one wild card: two things people here love combined, untested and never ranked.
 */
export interface Concept {
  name: string;
  genre: string;
  genre_id?: string | null;
  /** The category's gap score; null for the wild card, which is never ranked. */
  gap_score: number | null;
  one_liner?: string;
  for_whom?: string;
  why_here?: unknown;
  /** Who it competes with inside the walk; its last sentence names what the places people here love are known for
   * and none inside the walk is. */
  beat_competitors?: string;
  signature?: unknown;
  inspired_by?: unknown;
  risk?: string;
  /** How it meets each rule the owner gave, one plain line each: the unit, the kitchen, the price band, the diet. */
  owner_rules?: unknown;
  /** The extra concept after the ranked ones. */
  wildcard?: boolean;
  /** For the wild card: the two loves it combines. */
  combines?: LoveItem[] | null;
  /** For the wild card: why it is untested. */
  caution?: string | null;
}

export interface ConceptsPayload {
  concepts?: Concept[];
  mode?: string;
  note?: string;
  /** A plain warning when even the best concept rests on a weak gap. */
  caution?: string;
  model?: string | null;
  replayed_from?: number | null;
  /** What was repaired, replaced or dropped to keep to the evidence and the owner's rules, in plain words. */
  notes?: unknown;
}

export interface BaselineConcept {
  name?: string;
  genre?: string;
}

/**
 * The site and brief as the server read them, sent with the run event. A recorded run can come from another version of
 * the app, so the brief's values are checked before use.
 */
export interface RunSite {
  lat: number;
  lon: number;
  label: string;
  focus?: string;
  notes?: string;
  minutes?: number;
  size_m2?: number | null;
  kitchen?: string | null;
  outdoor?: boolean | null;
  intent?: string;
  business?: string;
  place_id?: string;
  /** Missing on older surveys: a walk, for everyone. */
  travel?: string;
  km?: number | null;
  ages?: string;
}

export interface RunPayload {
  run_id: string;
  llm: boolean;
  /** What the server read from the owner's notes as rules ("no alcohol", "budget prices"). */
  understood?: string[];
  site?: RunSite;
  /** "10-minute walk", "30-minute drive", "25 km drive". */
  area_label?: string;
  /** "Under 25", "25–34", "35–54", "55+"; null when the survey is for everyone. */
  ages_label?: string | null;
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
  /** Answers fetched from Qloo during this survey; `cache_hits` were Qloo answers already saved. */
  qloo_calls: number;
  cache_hits: number;
  /** Every Qloo answer the survey read (missing from surveys saved before it was counted). */
  qloo_queries?: number;
  /** When the oldest of those answers came from Qloo, ISO 8601. */
  data_as_of?: string | null;
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

export type RunStatus = "running" | "complete" | "failed";

/** One server-sent event of a recorded run: its name, its data and its time in seconds since the run started. */
export type RecordedEvent = [event: string, data: unknown, t: number];

/** A survey run as the server recorded it (GET /api/runs/{id}); its events grow while it runs. */
export interface RunRecord {
  id: string;
  status: RunStatus;
  created_at: string;
  events: RecordedEvent[];
}

export interface RunRequest {
  lat: number;
  lon: number;
  label: string;
  focus: Focus;
  notes: string;
  /** The walk or the drive in minutes, 5 to 60; unused for a road distance. */
  minutes: number;
  intent: Intent;
  /** The business to open (intent "open"). */
  business?: string;
  /** The owner's place on Qloo (intent "improve"). */
  placeId?: string;
  sizeM2?: number;
  kitchen?: Kitchen;
  outdoor?: boolean;
  /** Walk and drive take `minutes` (5–60); distance takes `km` (1–100). */
  travel?: Travel;
  km?: number;
  ages?: Ages;
}

/** How many of the places locals love carry one of Qloo's tags: who they draw, when people go, or why. */
export interface TagShare {
  label: string;
  places: number;
  of: number;
}

export type ClaimKind = "only" | "new" | "closer" | "promise";

/** A line an ad can say, with the numbers that make it true today. */
export interface LaunchClaim {
  kind: ClaimKind;
  line: string;
  proof: string;
}

/** One ad platform's targeting settings, ready to paste. */
export interface LaunchChannel {
  channel: string;
  setting: string;
  why: string;
}

export interface LaunchPlan {
  audience: {
    crowd: TagShare[];
    artists: string[];
    podcasts: string[];
    screen: string[];
    brands: string[];
    /** Names this category's fans love too. */
    shared: string[];
    /** Who the loved places of this kind draw. */
    people?: Audience | null;
  };
  where: {
    /** "10-minute walk", "30-minute drive", "25 km drive". */
    label?: string;
    minutes: number;
    reach_m: number | null;
    neighborhoods: string[];
    sites_like: { name: string; url: string }[];
  };
  when: {
    times: TagShare[];
    intents: (TagShare & { angle?: string | null })[];
    hours?: string | null;
  };
  claims: LaunchClaim[];
  channels: LaunchChannel[];
  cautions: string[];
  basis?: string;
}

/** The unit as the owner described it: "60 m² (646 ft²)", "a light-prep kitchen", and "yes", "none" or "unknown". */
export interface UnitText {
  size: string;
  kitchen: string;
  outdoor_space: string;
}

/**
 * A concept's design sheet (POST /api/design): what it sells, when it opens, what the unit holds, how it keeps the
 * owner's rules, what to play, screen and host, and how it launches. Sheets saved before the cuts may carry an interior,
 * a mood board, renders or prices too: those are never read.
 */
export interface Design {
  name?: string;
  /** The concept's one-liner. */
  tagline?: string | null;
  /** The concept's signature first, then what the places people here love are known for. */
  offer?: unknown;
  hours?: string | null;
  hours_basis?: string | null;
  unit?: UnitText | null;
  /** "about 27–32 seated guests at most", when the owner gave the unit's size. */
  capacity?: string | null;
  capacity_basis?: string | null;
  experience?: ExperiencePlan | null;
  launch?: LaunchPlan | null;
  /** Who the loved places of this kind draw: the people to win. */
  audience?: Audience | null;
  /** How the concept keeps each rule the owner gave, one plain line each. */
  owner_rules?: unknown;
  /** "rules"; sheets made before the cuts may say "agent". */
  mode?: string;
  model?: string | null;
}