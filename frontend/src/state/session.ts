import { useSyncExternalStore } from "react";
import { account, type AppConfig, type Me, type User } from "../api/account";
import { plainError } from "../lib/account";

export type SessionPhase = "loading" | "ready" | "failed";

/** The app's public settings and who is signed in, loaded once when the app starts. */
export interface Session {
  phase: SessionPhase;
  config: AppConfig | null;
  user: User | null;
  /** A sign-in, sign-out or account deletion is under way. */
  busy: boolean;
  /** Why the settings, or the last sign-in, sign-out or deletion, failed, in plain words; null when nothing did. */
  error: string | null;
}

/** The requests the session makes; tests pass stand-ins. */
export interface SessionApi {
  config: () => Promise<AppConfig>;
  me: () => Promise<{ user: User | null }>;
  signInGoogle: (credential: string) => Promise<Me>;
  signInDev: (email: string, name: string) => Promise<Me>;
  signOut: () => Promise<unknown>;
  deleteMe: () => Promise<unknown>;
}

export interface SessionStore {
  get: () => Session;
  subscribe: (listener: () => void) => () => void;
  /** Loads the settings and who is signed in: once, and again only after the settings failed to load. */
  load: () => Promise<void>;
  /** Asks the server again who is signed in, say after a request answered 401. */
  refresh: () => Promise<void>;
  /** Each resolves to whether it worked; why it did not is the session's `error`. */
  signInWithGoogle: (credential: string) => Promise<boolean>;
  signInDev: (email: string, name: string) => Promise<boolean>;
  signOut: () => Promise<boolean>;
  /** Deletes the account and the surveys saved to it; the session is then signed out. */
  deleteAccount: () => Promise<boolean>;
  clearError: () => void;
}

export const INITIAL_SESSION: Session = { phase: "loading", config: null, user: null, busy: false, error: null };

export function createSessionStore(api: SessionApi): SessionStore {
  let state = INITIAL_SESSION;
  let loading: Promise<void> | null = null;
  // Every sign-in, sign-out and deletion moves this on, so an answer to "who is signed in" asked before one never
  // undoes it.
  let generation = 0;
  const listeners = new Set<() => void>();

  function set(patch: Partial<Session>): void {
    state = { ...state, ...patch };
    for (const listener of listeners) listener();
  }

  function load(): Promise<void> {
    if (loading && state.phase !== "failed") return loading;
    set({ phase: "loading", error: null });
    const asked = generation;
    loading = Promise.allSettled([api.config(), api.me()]).then(([config, me]) => {
      if (me.status === "fulfilled" && asked === generation) set({ user: me.value.user });
      if (config.status === "fulfilled") set({ phase: "ready", config: config.value });
      else set({ phase: "failed", error: plainError(config.reason, "Walk-in's settings could not be loaded.") });
    });
    return loading;
  }

  async function refresh(): Promise<void> {
    const asked = generation;
    try {
      const { user } = await api.me();
      if (asked === generation) set({ user });
    } catch {
      // A failed check leaves the session as it was.
    }
  }

  async function signIn(attempt: () => Promise<Me>, failure: string): Promise<boolean> {
    generation += 1;
    set({ busy: true, error: null });
    try {
      const { user } = await attempt();
      set({ user, busy: false });
      return true;
    } catch (error) {
      set({ busy: false, error: plainError(error, failure) });
      return false;
    }
  }

  /** Signing out and deleting both end with nobody signed in; a failure keeps the user signed in and says why. */
  async function leave(attempt: () => Promise<unknown>, failure: string): Promise<boolean> {
    generation += 1;
    set({ busy: true, error: null });
    try {
      await attempt();
      set({ user: null, busy: false });
      return true;
    } catch (error) {
      set({ busy: false, error: plainError(error, failure) });
      return false;
    }
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
    refresh,
    signInWithGoogle: (credential) =>
      signIn(() => api.signInGoogle(credential), "Google sign-in did not go through. Try again."),
    signInDev: (email, name) => signIn(() => api.signInDev(email, name), "Signing in did not work. Try again."),
    signOut: () => leave(api.signOut, "Signing out did not work. Try again."),
    deleteAccount: () => leave(api.deleteMe, "Your account could not be deleted. Nothing was removed; try again."),
    clearError: () => {
      if (state.error !== null) set({ error: null });
    },
  };
}

/** The app's one session. */
export const session = createSessionStore(account);

export function useSession(): Session {
  return useSyncExternalStore(session.subscribe, session.get, session.get);
}
