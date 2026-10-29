/* The launch kit: its payload (app/survey/kit.py's build_kit, and the dossier it carries, app/survey/dossier.py), and
   the free kit API that makes one for a survey's concept and serves it to anyone with its link. */
import { fetched, post, request } from "./client";
import type { KitCampaign } from "./founders";
import type { ClaimKind, LatLon, LaunchChannel, LaunchPlan, UnitText, VerdictLevel } from "./types";

/** A launch-plan claim with its id ("only", "new-1"…), which the copy lists when it leans on it. */
export interface KitClaim {
  id: string;
  kind: ClaimKind;
  line: string;
  proof: string;
}

/** Who wrote a piece: the model, the evidence rules, or the model with lines topped up by the rules. */
export type CopySource = "agent" | "rules" | "mixed";

interface CopyPiece {
  /** The channel's name, as the launch plan calls it ("Spotify Ads"). */
  channel: string;
  claims: string[];
  source: CopySource;
}

export interface SpotifyCopy extends CopyPiece {
  script: string;
  companion: string;
  words: number;
  seconds: number;
}

export interface NextdoorCopy extends CopyPiece {
  headline: string;
  body: string;
}

export interface GoogleSearchCopy extends CopyPiece {
  headlines: string[];
  descriptions: string[];
}

export interface MetaCopy extends CopyPiece {
  primary_text: string;
  headline: string;
  description: string;
}

export interface PosterCopy extends CopyPiece {
  headline: string;
  subline: string;
}

/** One piece per channel of the launch plan, and always the poster. */
export interface KitCopy {
  spotify?: SpotifyCopy;
  nextdoor?: NextdoorCopy;
  google_search?: GoogleSearchCopy;
  meta?: MetaCopy;
  poster?: PosterCopy;
}

export type ChannelKey = keyof KitCopy;

/** What the window poster says, and the walk it is drawn from: [lat, lon] points in the order they were traced. */
export interface KitPoster {
  name: string;
  tagline: string | null;
  headline: string | null;
  subline: string | null;
  claim: { kind: ClaimKind; line: string; proof: string } | null;
  hours: string | null;
  minutes: number;
  /** "10-minute walk", "30-minute drive", "25 km drive"; missing on older kits. */
  area_label?: string;
  ring: LatLon[];
  site: LatLon;
  neighborhoods: string[];
}

/** A channel's UTM tags; the owner's website goes in front of `query`. */
export interface KitLink {
  key: ChannelKey;
  channel: string;
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
  query: string;
}

/** A line the model wrote that broke a rule, and why. */
export interface RejectedLine {
  channel: string;
  field: string;
  text: string;
  reasons: string[];
  attempt?: number;
}

export interface Kit {
  concept: { index: number; name: string; genre: string };
  claims: KitClaim[];
  copy: KitCopy;
  poster: KitPoster;
  links: KitLink[];
  dossier: Dossier;
  rejected: RejectedLine[];
  /** Claims left out, and why. */
  notes: string[];
  mode: "agent" | "rules";
  model: string | null;
  built_at: string;
}

// ---------- The dossier: twelve sections, each with the basis a reader can check it by ----------

export type DossierKey =
  | "cover"
  | "case"
  | "alternatives"
  | "competition"
  | "travel"
  | "offer"
  | "room"
  | "experience"
  | "launch"
  | "first_90_days"
  | "before_you_sign"
  | "method";

interface Based {
  basis: string;
}

export interface DossierCover extends Based {
  concept: string;
  genre: string;
  tagline: string | null;
  site_label: string;
  lat: number;
  lon: number;
  walk_minutes: number;
  /** "10-minute walk", "30-minute drive", "25 km drive"; missing on older kits. */
  area_label?: string;
  walk_source: string | null;
  area_km2: number | null;
  reach_m: number | null;
  ring: LatLon[];
  neighborhoods: string[];
  evidence_date: string;
  prepared_date: string;
  sources: { name: string; used_for: string }[];
}

/** The verdict when the owner asked to open this business, else where it ranks among the site's gaps. */
export interface DossierDecision extends Based {
  kind: "verdict" | "gap";
  stamp: string;
  level?: VerdictLevel;
  reason: string;
  rank?: number | null;
  of?: number | null;
  gap_score?: number | null;
  /** The business the owner asked about, when the dossier covers another. */
  asked?: { business: string; stamp: string; reason: string | null };
}

/** One of the case's numbers: Demand, Supply, Pull or Capacity, each with its basis. */
export interface DossierNumber extends Based {
  label: string;
  value: string;
  data?: unknown;
}

export interface DossierCase extends Based {
  decision: DossierDecision;
  numbers: DossierNumber[];
  who: { text: string; basis: string };
  risk: { text: string; check: string; basis: string };
  caution?: string;
}

export interface DossierAlternative {
  genre: string;
  gap_score: number;
  reading: string;
  position: number | null;
  why: string;
  chosen: boolean;
  tested_live?: boolean;
  why_not?: string;
}

export interface DossierAlternatives extends Based {
  items: DossierAlternative[];
}

export interface DossierComplaint {
  theme: string;
  mentions: number | null;
  keywords: string[];
}

export interface DossierRival {
  name: string;
  url: string | null;
  link: "menu" | "site" | null;
  rating: number | null;
  known_for: string[];
  complaints: DossierComplaint[];
  distance_m: number | null;
  /** One of the places that compete in earnest, rather than one that only sells it on the side. */
  main: boolean;
}

export interface DossierTheme {
  theme: string;
  places: number;
  mentions: number | null;
}

export interface DossierPromise extends DossierTheme {
  promise: string;
  move: string | null;
}

export interface DossierCompetition extends Based {
  places: DossierRival[];
  count: number;
  capped: boolean;
  themes: DossierTheme[];
  your_answer?: { promises: DossierPromise[]; basis: string };
}

export interface DossierTravelPlace {
  name: string;
  url: string | null;
  link: "menu" | "site" | null;
  km: number | null;
  known_for: string[];
}

export interface DossierTravel extends Based {
  places: DossierTravelPlace[];
  outside: number;
  of: number;
  median_km: number | null;
}

export interface DossierOfferItem {
  item: string;
  places: number;
  of: number;
  new_here: boolean;
}

export interface DossierSheetItem {
  item: string;
  places: number | null;
  new_here: boolean | null;
}

/** What to sell: what the places locals love are known for, and the design sheet's offer matched against it. */
export interface DossierOffer extends Based {
  items: DossierOfferItem[];
  sheet: DossierSheetItem[];
}

/** The unit as the owner described it, what it holds and when to open. */
export interface DossierRoom extends Based {
  unit?: UnitText;
  capacity?: string;
  capacity_basis?: string;
  hours?: string;
  hours_basis?: string | null;
}

export interface DossierExperience extends Based {
  soundtrack?: string[];
  screen?: string[];
  talks?: string[];
  licensing?: string;
}

export interface DossierLaunch extends Based {
  claims: KitClaim[];
  audience?: LaunchPlan["audience"] | null;
  where?: LaunchPlan["where"] | null;
  when?: LaunchPlan["when"] | null;
  channels: LaunchChannel[];
  cautions: string[];
  notes?: string[];
  copy?: KitCopy;
}

export interface DossierStep {
  when: string;
  do: string;
  basis: string;
}

export interface DossierFirst90 extends Based {
  steps: DossierStep[];
}

export interface DossierBeforeYouSign extends Based {
  questions: { ask: string; basis: string }[];
  checks?: { risk: string; check: string; basis: string }[];
}

export interface DossierMethod extends Based {
  items: { topic: string; how: string }[];
  freshness: string;
  limits: string[];
}

/** Only the sections the evidence supports are present; `sections` lists them in order. */
export interface Dossier {
  sections: DossierKey[];
  cover?: DossierCover;
  case?: DossierCase;
  alternatives?: DossierAlternatives;
  competition?: DossierCompetition;
  travel?: DossierTravel;
  offer?: DossierOffer;
  room?: DossierRoom;
  experience?: DossierExperience;
  launch?: DossierLaunch;
  first_90_days?: DossierFirst90;
  before_you_sign?: DossierBeforeYouSign;
  method?: DossierMethod;
}

// ---------- The kit API: free, and open to anyone with a kit's link ----------

export type KitStatus = "building" | "ready" | "failed";

/** POST /api/kits: the kit for a survey's concept, made now or found. */
export interface KitMade {
  token: string;
  /** /k/{token} */
  url: string;
  status: KitStatus;
}

/** GET /api/kits/{token}. */
export interface KitView {
  token: string;
  status: KitStatus;
  survey_id: string;
  index: number;
  /** The business's name. */
  name: string;
  created_at: string;
  /** /s/{survey_id}?sheet={index} */
  survey_url: string;
  /** The contents, once ready. */
  kit: Kit | null;
  /** Why it failed, in plain words. */
  error: string | null;
  /**
   * The kit's open Founders campaigns, the viewer's own first: not part of the kit's page (GET /api/kits/{token}/campaigns,
   * state/kit.ts adds them), and missing until they have arrived.
   */
  campaigns?: KitCampaign[];
}

/** A kit as My places lists it (GET /api/me/places). */
export interface PlacesKit {
  token: string;
  survey_id: string;
  index: number;
  name: string;
  status: KitStatus;
  created_at: string;
  /** /k/{token} */
  url: string;
}

const segment = (text: string) => encodeURIComponent(text);

/** Where a kit is read, and fetched ahead. */
export const kitPath = (token: string) => `/api/kits/${segment(token)}`;

export const kits = {
  /** Makes the kit for a survey's concept, or returns the one it already has; 429 when this address made too many. */
  make: (runId: string, index: number) => request<KitMade>("/api/kits", post({ run_id: runId, index })),
  /** The kit a survey's concept already has, if any. */
  find: (runId: string, index: number, signal?: AbortSignal) =>
    request<{ kit_url: string | null }>(`/api/kits?${new URLSearchParams({ run_id: runId, index: String(index) }).toString()}`, {
      signal,
    }),
  /** A kit by its token, or as it was fetched ahead. */
  get: async (token: string, signal?: AbortSignal) => (await fetched(kitPath(token), signal)) as KitView,
  /** Builds a kit that failed again (202); 409 when it is not a failed kit any more, 429 when this address made too many. */
  retry: (token: string) => request<KitMade>(`/api/kits/${segment(token)}/retry`, post()),
};
