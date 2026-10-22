import { useSyncExternalStore } from "react";
import { ENGINE_ASLEEP, probeEngine, sleep, WAKE_BUDGET_MS, watchEngine, type EngineProbe, type EngineWatcher } from "../api/client";

/** Where the backend stands, as far as the app knows: not asked yet, being asked, napping, awake, or not waking. */
export type EnginePhase = "unknown" | "checking" | "waking" | "ready" | "asleep";
/** What the top bar says about it: nothing, the waking note, "Ready" (then it fades), or that it would not wake. */
export type EngineNote = "none" | "waking" | "ready" | "leaving" | "asleep";

export interface Engine {
  phase: EnginePhase;
  note: EngineNote;
  /** When this wake-up began, on the store's clock: the note counts its seconds from here. */
  since: number;
}

/** What the store uses to look and to wait; tests pass stand-ins. */
export interface EngineDeps {
  probe: (signal: AbortSignal) => Promise<EngineProbe>;
  now: () => number;
  sleep: (ms: number, signal?: AbortSignal | null) => Promise<boolean>;
  /** Runs `run` after `ms`; the function it returns cancels that. */
  later: (ms: number, run: () => void) => () => void;
}

export interface EngineStore {
  get: () => Engine;
  subscribe: (listener: () => void) => () => void;
  /** Looks once at app start; the note shows only if the engine has not answered within NOTE_AFTER_MS. */
  start: () => void;
  /** Looks again after the store gave up: the Retry button. */
  retry: () => void;
  /**
   * Resolves once the engine is awake: at once when it answered in the last few minutes, otherwise after a fresh look
   * (and a wait while it wakes). Rejects with ENGINE_ASLEEP if it does not wake, or as the signal aborts.
   */
  whenReady: (signal?: AbortSignal) => Promise<void>;
  /** What every request tells the store (api/client.ts). */
  watcher: EngineWatcher;
}

/** No answer by then and the note shows: most answers come well before, and a note that flashes by is noise. */
export const NOTE_AFTER_MS = 1500;
/** The engine is asked again this long after each answer while it wakes. */
export const POLL_MS = 2000;
/** A single look gives up after this long, and the next one goes out. */
export const PROBE_MS = 20_000;
/** An engine that answered this recently is taken to be awake: Render puts it to sleep after 15 quiet minutes. */
export const FRESH_MS = 5 * 60_000;
/** "Ready" stays this long once the engine wakes, then the note fades out over FADE_MS. */
export const READY_MS = 1600;
export const FADE_MS = 700;

export const INITIAL_ENGINE: Engine = { phase: "unknown", note: "none", since: 0 };

interface Waiter {
  resolve: () => void;
  reject: (error: Error) => void;
}

const aborted = () => new DOMException("The wait was aborted.", "AbortError");

export function createEngineStore(deps: EngineDeps): EngineStore {
  let state = INITIAL_ENGINE;
  /** When the engine last answered anything, on the store's clock. */
  let heardAt = Number.NEGATIVE_INFINITY;
  /** Each wake-up's number: an answer that settles it, or a newer one, stops the older one's looking. */
  let round = 0;
  let looking: AbortController | null = null;
  let cancelNote: (() => void) | null = null;
  let cancelFade: (() => void) | null = null;
  const listeners = new Set<() => void>();
  const waiters = new Set<Waiter>();

  function set(patch: Partial<Engine>): void {
    state = { ...state, ...patch };
    for (const listener of listeners) listener();
  }

  /** Stops the current wake-up's looking and its timers. */
  function stop(): void {
    round += 1;
    looking?.abort();
    looking = null;
    cancelNote?.();
    cancelNote = null;
    cancelFade?.();
    cancelFade = null;
  }

  function show(): void {
    cancelNote?.();
    cancelNote = null;
    set({ phase: "waking", note: "waking" });
  }

  function awake(): void {
    const shown = state.note === "waking" || state.note === "asleep";
    stop();
    heardAt = deps.now();
    set({ phase: "ready", note: shown ? "ready" : "none" });
    for (const waiter of waiters) waiter.resolve();
    waiters.clear();
    if (!shown) return;
    cancelFade = deps.later(READY_MS, () => {
      set({ note: "leaving" });
      cancelFade = deps.later(FADE_MS, () => {
        cancelFade = null;
        set({ note: "none" });
      });
    });
  }

  function giveUp(): void {
    stop();
    set({ phase: "asleep", note: "asleep" });
    for (const waiter of waiters) waiter.reject(new Error(ENGINE_ASLEEP));
    waiters.clear();
  }

  /** Asks /api/health every POLL_MS until it answers, for up to WAKE_BUDGET_MS. */
  async function poll(mine: number, signal: AbortSignal): Promise<void> {
    for (;;) {
      const left = WAKE_BUDGET_MS - (deps.now() - state.since);
      const attempt = new AbortController();
      const end = () => {
        attempt.abort();
      };
      signal.addEventListener("abort", end);
      const cancel = deps.later(Math.max(1000, Math.min(PROBE_MS, left)), end);
      const outcome = await deps.probe(attempt.signal);
      cancel();
      signal.removeEventListener("abort", end);
      if (mine !== round) return;
      if (outcome === "ready") {
        awake();
        return;
      }
      if (outcome === "waking" && state.phase === "checking") show();
      if (deps.now() + POLL_MS - state.since >= WAKE_BUDGET_MS) {
        giveUp();
        return;
      }
      if (!(await deps.sleep(POLL_MS, signal)) || mine !== round) return;
    }
  }

  /** Starts looking, unless a look is already under way; `napping` says so on screen at once. */
  function check(napping: boolean): void {
    if (state.phase === "checking" || state.phase === "waking") {
      if (napping && state.phase === "checking") show();
      return;
    }
    stop();
    const mine = round;
    const controller = new AbortController();
    looking = controller;
    set({ phase: napping ? "waking" : "checking", note: napping ? "waking" : "none", since: deps.now() });
    if (!napping) {
      cancelNote = deps.later(NOTE_AFTER_MS, () => {
        cancelNote = null;
        if (mine === round && state.phase === "checking") show();
      });
    }
    void poll(mine, controller.signal);
  }

  const fresh = () => state.phase === "ready" && deps.now() - heardAt <= FRESH_MS;

  return {
    get: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => {
      if (state.phase === "unknown") check(false);
    },
    retry: () => {
      if (state.phase === "asleep") check(true);
    },
    whenReady: (signal) => {
      if (signal?.aborted) return Promise.reject(aborted());
      if (fresh()) return Promise.resolve();
      check(state.phase === "asleep");
      return new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          waiters.delete(waiter);
          reject(aborted());
        };
        const waiter: Waiter = {
          resolve: () => {
            signal?.removeEventListener("abort", onAbort);
            resolve();
          },
          reject: (error) => {
            signal?.removeEventListener("abort", onAbort);
            reject(error);
          },
        };
        waiters.add(waiter);
        signal?.addEventListener("abort", onAbort, { once: true });
      });
    },
    watcher: {
      asking: () => {
        if (state.phase === "ready" && !fresh()) check(false);
      },
      answered: () => {
        heardAt = deps.now();
        if (state.phase !== "ready") awake();
      },
      waking: () => {
        check(true);
      },
    },
  };
}

/** The app's one engine store, told about every request the API helpers make. */
export const engine = createEngineStore({
  probe: (signal) => probeEngine(signal),
  now: () => Date.now(),
  sleep,
  later: (ms, run) => {
    const timer = setTimeout(run, ms);
    return () => {
      clearTimeout(timer);
    };
  },
});
watchEngine(engine.watcher);

export function useEngine(): Engine {
  return useSyncExternalStore(engine.subscribe, engine.get, engine.get);
}
