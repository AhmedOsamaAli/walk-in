/* Answers fetched ahead of a click: a survey's record and a launch kit, asked for when a link to them is hovered, focused
   or touched, when the examples sit idle on screen, or as a page opens on one, so opening it shows from memory rather
   than after a round trip. Only what no longer changes is kept for later views (a finished survey, a ready kit), and for
   a minute, as long as the backend lets a browser keep the least lasting of them (app/cache_policy.py); every other
   answer serves the view already waiting for it, then goes. */

export const PREFETCH_TTL_MS = 60_000;
/** Answers kept at most; the oldest goes first. */
export const PREFETCH_MAX = 16;

interface Entry {
  at: number;
  answer: Promise<unknown>;
}

export interface PrefetchCache {
  /** Starts fetching `path` unless its answer is kept or on its way. */
  prefetch: (path: string) => void;
  /** The answer for `path`, kept or on its way; null when there is none and it must be asked for. */
  take: (path: string) => Promise<unknown> | null;
}

export interface PrefetchDeps {
  fetch: (path: string) => Promise<unknown>;
  /** Whether an answer can be kept for later views: it no longer changes. */
  keep: (path: string, body: unknown) => boolean;
  now: () => number;
}

export function createPrefetchCache({ fetch, keep, now }: PrefetchDeps): PrefetchCache {
  const entries = new Map<string, Entry>();

  function live(path: string): Entry | null {
    const entry = entries.get(path);
    if (!entry) return null;
    if (now() - entry.at <= PREFETCH_TTL_MS) return entry;
    entries.delete(path);
    return null;
  }

  function drop(path: string, entry: Entry): void {
    if (entries.get(path) === entry) entries.delete(path);
  }

  return {
    prefetch: (path) => {
      if (live(path)) return;
      const entry: Entry = { at: now(), answer: fetch(path) };
      entries.set(path, entry);
      // A Map keeps its keys in the order they came: the first is the oldest.
      for (const old of entries.keys()) {
        if (entries.size <= PREFETCH_MAX) break;
        entries.delete(old);
      }
      entry.answer.then(
        (body) => {
          if (!keep(path, body)) drop(path, entry);
        },
        () => {
          drop(path, entry);
        },
      );
    },
    take: (path) => live(path)?.answer ?? null,
  };
}

/** The states of a survey that has ended: its record no longer changes. */
const FINISHED: ReadonlySet<unknown> = new Set(["complete", "failed"]);

/** Whether an answer can be kept: a finished survey's record, or a kit that is ready and came with its contents. */
export function settled(path: string, body: unknown): boolean {
  if (typeof body !== "object" || body === null || !("status" in body)) return false;
  if (path.startsWith("/api/runs/")) return FINISHED.has(body.status);
  if (path.startsWith("/api/kits/")) return body.status === "ready" && "kit" in body && typeof body.kit === "object" && body.kit !== null;
  return false;
}
