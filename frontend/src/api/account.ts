/* Accounts: the app's public settings, who is signed in, and the surveys saved to the account (the API contract). */
import { post, request } from "./client";
import type { Intent, RunStatus } from "./types";

/** GET /api/config: the web app's public settings, limited to what signing in needs. */
export interface AppConfig {
  google_client_id: string | null;
  /** Development sign-in by email: never on the hosted site. */
  dev_login: boolean;
}

export interface User {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

export interface Me {
  user: User;
}

/** A survey saved to the account. */
export interface PlacesSurvey {
  id: string;
  /** The place the survey was run for, as the brief named it. */
  label: string;
  intent: Intent;
  status: RunStatus;
  created_at: string;
  /** The top concept's name, or the top gap; null while it runs or when it found none. */
  headline: string | null;
  /** /s/{id} */
  url: string;
}

/** GET /api/me/places: newest first, at most 100. */
export interface Places {
  surveys: PlacesSurvey[];
}

export const account = {
  config: () => request<AppConfig>("/api/config"),
  /** Never 401: `user` is null when nobody is signed in. */
  me: () => request<{ user: User | null }>("/api/me"),
  signInGoogle: (credential: string) => request<Me>("/api/auth/google", post({ credential })),
  signInDev: (email: string, name: string) => request<Me>("/api/auth/dev", post({ email, name })),
  signOut: () => request<undefined>("/api/auth/logout", post()),
  /** Deletes the account and the surveys saved to it (204). */
  deleteMe: () => request<undefined>("/api/me", { method: "DELETE" }),
  places: (signal?: AbortSignal) => request<Places>("/api/me/places", { signal }),
};
