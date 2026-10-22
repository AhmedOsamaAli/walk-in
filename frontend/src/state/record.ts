import { ApiError, messageOf } from "../api/client";
import type { RunRecord } from "../api/types";
import type { SurveyAction } from "./survey";

export const POLL_MS = 2000;
/** A run that records no event for this long has stopped, say because its server restarted mid-run. */
export const STALL_MS = 5 * 60_000;
/** Polls that fail in a row before the survey is given up. */
export const POLL_TRIES = 5;

export const RUN_GONE = "This survey is no longer available.";
export const RUN_STALLED = "The survey stopped sending updates before it finished.";

/** What following a running record needs; the hook passes the network and timers, tests pass stand-ins. */
export interface Poll {
  /** The record's latest copy. */
  load: () => Promise<RunRecord>;
  /** Waits for the next poll; resolves false once following was cancelled. */
  wait: () => Promise<boolean>;
  dispatch: (action: SurveyAction) => void;
  /** A clock in milliseconds. */
  now: () => number;
  /** Seconds since the run started, for the log line of a failure. */
  at: () => number;
  cancelled: () => boolean;
}

/**
 * Polls a recorded run until it ends, passing on each copy that brings something new; the reducer applies only the
 * events it has not seen. A run that disappears, keeps failing to load or goes silent is reported as stopped.
 */
export async function followRecord(first: RunRecord, poll: Poll): Promise<void> {
  let seen = first.events.length;
  let changed = poll.now();
  let failures = 0;
  while (await poll.wait()) {
    let record: RunRecord;
    try {
      record = await poll.load();
    } catch (error) {
      if (poll.cancelled()) return;
      const gone = error instanceof ApiError && error.status === 404;
      failures += 1;
      if (gone || failures >= POLL_TRIES) {
        poll.dispatch({ type: "failed", message: gone ? RUN_GONE : messageOf(error), at: poll.at() });
        return;
      }
      continue;
    }
    if (poll.cancelled()) return;
    failures = 0;
    const ended = record.status !== "running";
    if (ended || record.events.length > seen) poll.dispatch({ type: "recorded", record });
    if (ended) return;
    if (record.events.length > seen) {
      seen = record.events.length;
      changed = poll.now();
    } else if (poll.now() - changed >= STALL_MS) {
      poll.dispatch({ type: "failed", message: RUN_STALLED, at: poll.at() });
      return;
    }
  }
}

/** An ISO time without a zone is the server's UTC, not the browser's local time. */
function utcTime(iso: string): number {
  return Date.parse(/(?:z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`);
}

/**
 * Seconds since a recorded run started, for the live timer. While it runs that is the clock since `created_at`, unless
 * the two clocks disagree so much that the time of its last event is the better guess; once it has ended, the latter.
 */
export function recordElapsed(record: RunRecord, now: number): number {
  const last = record.events.at(-1)?.[2] ?? 0;
  if (record.status !== "running") return last;
  const since = (now - utcTime(record.created_at)) / 1000;
  return Number.isFinite(since) && since >= last && since - last < STALL_MS / 1000 ? since : last;
}
