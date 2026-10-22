import { useCallback, useEffect, useReducer, useRef, type Dispatch, type RefObject } from "react";
import { api, ApiError, messageOf, openRun } from "../api/client";
import { readEvents, toSurveyEvent } from "../api/stream";
import type { RunRecord, RunRequest } from "../api/types";
import { followRecord, POLL_MS, recordElapsed, type Poll } from "./record";
import { initialSurvey, surveyReducer, type SurveyAction, type SurveyState } from "./survey";

/** How opening a survey's link went: shown, gone from the server, not loaded, or overtaken by another survey. */
export type RestoreResult =
  | { outcome: "shown" }
  | { outcome: "missing" }
  | { outcome: "failed"; message: string }
  | { outcome: "superseded" };

export interface Survey {
  survey: SurveyState;
  start: (run: RunRequest) => void;
  /** Shows a recorded survey and follows it while it runs; resolves once it is on screen, or with why it is not. */
  restore: (id: string) => Promise<RestoreResult>;
  reset: () => void;
  toggleGap: (index: number) => void;
}

/** Abandons the run being streamed or followed, and makes a new controller the current one. */
function takeOver(current: RefObject<AbortController | null>): AbortController {
  current.current?.abort();
  const abort = new AbortController();
  current.current = abort;
  return abort;
}

function release(current: RefObject<AbortController | null>, abort: AbortController): void {
  if (current.current === abort) current.current = null;
}

/** Resolves true after `ms`, or false as soon as the signal aborts. */
function pause(ms: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const cancel = () => {
      window.clearTimeout(timer);
      resolve(false);
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve(true);
    }, ms);
    signal.addEventListener("abort", cancel, { once: true });
  });
}

function poller(id: string, abort: AbortController, startedAt: number, dispatch: Dispatch<SurveyAction>): Poll {
  return {
    load: () => api.run(id, abort.signal),
    wait: () => pause(POLL_MS, abort.signal),
    dispatch: (action) => {
      if (!abort.signal.aborted) dispatch(action);
    },
    now: () => performance.now(),
    at: () => (performance.now() - startedAt) / 1000,
    cancelled: () => abort.signal.aborted,
  };
}

/** Streams survey runs, or shows recorded ones, into the survey state; a new run, restore or reset abandons the last. */
export function useSurvey(): Survey {
  const [survey, dispatch] = useReducer(surveyReducer, initialSurvey);
  const controller = useRef<AbortController | null>(null);

  const start = useCallback((run: RunRequest) => {
    const abort = takeOver(controller);
    const startedAt = performance.now();
    const at = () => (performance.now() - startedAt) / 1000;
    dispatch({ type: "start", startedAt, intent: run.intent });
    void (async () => {
      try {
        const stream = await openRun(run, abort.signal);
        for await (const raw of readEvents(stream)) {
          const event = toSurveyEvent(raw);
          if (event && !abort.signal.aborted) dispatch({ type: "event", event, at: at() });
        }
        if (!abort.signal.aborted) dispatch({ type: "closed", at: at() });
      } catch (error) {
        if (!abort.signal.aborted) dispatch({ type: "failed", message: messageOf(error), at: at() });
      } finally {
        release(controller, abort);
      }
    })();
  }, []);

  const restore = useCallback(async (id: string): Promise<RestoreResult> => {
    const abort = takeOver(controller);
    dispatch({ type: "reset" });
    let record: RunRecord;
    try {
      record = await api.run(id, abort.signal);
    } catch (error) {
      release(controller, abort);
      if (abort.signal.aborted) return { outcome: "superseded" };
      if (error instanceof ApiError && error.status === 404) return { outcome: "missing" };
      return { outcome: "failed", message: messageOf(error) };
    }
    if (abort.signal.aborted) return { outcome: "superseded" };
    // The live timer counts from when the run started, not from when this page loaded it.
    const startedAt = performance.now() - recordElapsed(record, Date.now()) * 1000;
    dispatch({ type: "restore", record, startedAt });
    if (record.status !== "running") {
      release(controller, abort);
      return { outcome: "shown" };
    }
    void followRecord(record, poller(id, abort, startedAt, dispatch)).finally(() => {
      release(controller, abort);
    });
    return { outcome: "shown" };
  }, []);

  const reset = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    dispatch({ type: "reset" });
  }, []);

  const toggleGap = useCallback((index: number) => {
    dispatch({ type: "toggleGap", index });
  }, []);

  useEffect(() => {
    const runs = controller;
    return () => runs.current?.abort();
  }, []);

  return { survey, start, restore, reset, toggleGap };
}
