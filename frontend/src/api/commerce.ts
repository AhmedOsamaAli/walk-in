/* Payments only (the launch kit and pledge campaigns): the commerce API contract, limited to the fields this app reads.
   Accounts are in ./account, which nothing here is imported into. */
import type { AppConfig } from "./account";
import { ApiError, post, request } from "./client";
import type { Kit } from "./kit";

export interface PayPalConfig {
  /** False when PayPal is not configured on the server: buying and pledging are off. */
  enabled: boolean;
  /** The public REST client id the JS SDK needs. */
  client_id: string | null;
  /** "sandbox" or "production". */
  environment: string;
  currency: string;
  kit_price: string;
}

/** The `paypal` part of GET /api/config, which the session keeps whole; null when the server sent none. */
export function paypalOf(config: AppConfig | null): PayPalConfig | null {
  const paypal: unknown = config && "paypal" in config ? config.paypal : null;
  return typeof paypal === "object" && paypal !== null && "enabled" in paypal ? (paypal as PayPalConfig) : null;
}

export type KitStatus = "building" | "ready" | "failed" | "refunded";
export type CampaignStatus = "open" | "collected" | "partial" | "expired" | "cancelled";

/** The kits and campaigns GET /api/me/places lists beside the surveys. */
export interface PlacesKit {
  token: string;
  survey_id: string;
  index: number;
  /** The business's name. */
  name: string;
  status: KitStatus;
  created_at: string;
  url: string;
}

export interface PlacesCampaign {
  id: string;
  title: string;
  status: CampaignStatus;
  supporters: number;
  goal: number;
  deadline: string;
  url: string;
}

/** GET /api/kits/{token}: anyone with the link can read it. */
export interface KitView {
  token: string;
  status: KitStatus;
  survey_id: string;
  index: number;
  name: string;
  created_at: string;
  /** /s/{survey_id}?sheet={index} */
  survey_url: string;
  /** The signed-in user bought it. */
  is_owner: boolean;
  kit: Kit | null;
  /** Why it failed, in plain words. */
  error: string | null;
  campaign_url: string | null;
  /** Owner only: refunds are self-service until then. */
  refundable_until: string | null;
}

export interface CampaignProgress {
  supporters: number;
  goal: number;
  remaining: number;
  percent: number;
  /** The money held or collected, such as "200.00". */
  total: string;
  funded: boolean;
}

/** GET /api/campaigns/{id}: the public pledge page, with the owner's view when the owner reads it. */
export interface CampaignView {
  id: string;
  status: CampaignStatus;
  /** Still takes pledges. */
  accepting: boolean;
  name: string;
  neighborhood: string | null;
  concept: { genre: string; summary: string };
  title: string;
  pitch: string;
  perks: string[];
  how_it_works: string;
  amount: string;
  currency: string;
  goal: number;
  deadline: string;
  closed_at: string | null;
  progress: CampaignProgress;
  is_owner: boolean;
  owner?: {
    /** Pledges by status. */
    counts: Record<string, number>;
    /** The settlement report in plain words, once settled. */
    report: string[] | null;
  };
  survey_url: string;
}

/** The owner's terms: the amount, the goal, the deadline (ISO) and any founding-supporter discount. */
export interface CampaignTerms {
  kit_token: string;
  amount: string;
  goal: number;
  deadline: string;
  discount: string | null;
}

/** The words drafted for the page; `problems` says why the terms are not allowed, and then nothing is drafted. */
export interface CampaignDraft {
  title: string;
  pitch: string;
  perks: string[];
  how_it_works: string;
  problems: string[];
}

export interface CampaignText {
  title: string;
  pitch: string;
  perks: string[];
}

export interface PledgeHeld {
  status: "authorized";
  supporter_number: number;
  /** /p/{id}?withdraw={token} */
  withdraw_url: string;
  progress: CampaignProgress;
}

export interface PledgeWithdrawn {
  status: "voided";
  progress: CampaignProgress;
}

const path = (segment: string) => encodeURIComponent(segment);

export const commerce = {
  ownedKit: (runId: string, index: number, signal?: AbortSignal) =>
    request<{ kit_url: string | null }>(`/api/kits/mine?${new URLSearchParams({ run_id: runId, index: String(index) }).toString()}`, {
      signal,
    }),
  checkout: (runId: string, index: number) => request<{ order_id: string }>("/api/checkout", post({ run_id: runId, index })),
  capture: (orderId: string) => request<{ token: string; kit_url: string }>(`/api/checkout/${path(orderId)}/capture`, post()),
  kit: (token: string, signal?: AbortSignal) => request<KitView>(`/api/kits/${path(token)}`, { signal }),
  retryKit: (token: string) => request<unknown>(`/api/kits/${path(token)}/retry`, post()),
  refundKit: (token: string) => request<{ status: "refunded" }>(`/api/kits/${path(token)}/refund`, post()),

  draftCampaign: (terms: CampaignTerms) => request<CampaignDraft>("/api/campaigns/draft", post(terms)),
  createCampaign: (campaign: CampaignTerms & CampaignText) =>
    request<{ id: string; url: string }>("/api/campaigns", post(campaign)),
  campaign: (id: string, signal?: AbortSignal) => request<CampaignView>(`/api/campaigns/${path(id)}`, { signal }),
  pledge: (id: string) => request<{ order_id: string }>(`/api/campaigns/${path(id)}/pledges`, post()),
  authorizePledge: (id: string, orderId: string) =>
    request<PledgeHeld>(`/api/campaigns/${path(id)}/pledges/${path(orderId)}/authorize`, post()),
  withdraw: (id: string, token: string) => request<PledgeWithdrawn>(`/api/campaigns/${path(id)}/withdraw`, post({ token })),
  closeCampaign: (id: string) => request<CampaignView>(`/api/campaigns/${path(id)}/close`, post()),
  cancelCampaign: (id: string) => request<CampaignView>(`/api/campaigns/${path(id)}/cancel`, post()),
};

// ---------- What an error's body adds ----------

function field(error: unknown, name: string): unknown {
  if (!(error instanceof ApiError) || typeof error.body !== "object" || error.body === null) return undefined;
  return (error.body as Record<string, unknown>)[name];
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item: unknown) =>
      typeof item === "string"
        ? item
        : typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string"
          ? item.msg
          : "",
    )
    .filter((text) => text.trim() !== "");
}

/** A 402 that PayPal's buttons can recover from by restarting the payment (a declined card). */
export function canRetry(error: unknown): boolean {
  return error instanceof ApiError && error.status === 402 && field(error, "retry") === true;
}

/** The link a 409 sends with it: the kit the user already owns, or the campaign the kit already has. */
export function conflictUrl(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  for (const name of ["kit_url", "url", "campaign_url"]) {
    const value = field(error, name);
    if (typeof value === "string" && value.startsWith("/")) return value;
  }
  return null;
}

/** The problems a 422 lists, from `problems` or from a `detail` that is a list; else its one message. */
export function problemsOf(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const listed = strings(field(error, "problems"));
  if (listed.length) return listed;
  const detail = strings(field(error, "detail"));
  if (detail.length) return detail;
  return error.explained ? [error.message] : [];
}
