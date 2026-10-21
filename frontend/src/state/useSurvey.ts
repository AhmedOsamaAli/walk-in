import { useCallback, useEffect, useReducer, useRef } from "react";
import { messageOf, openRun } from "../api/client";
import { readEvents, toSurveyEvent } from "../api/stream";
import type { RunRequest } from "../api/types";
import { initialSurvey, surveyReducer, type SurveyState } from "./survey";

export interface Survey {
  survey: SurveyState;
  start: (run: RunRequest) => void;
  reset: () => void;
  toggleGap: (index: number) => void;
}

/** Streams survey runs into the survey state; a new run or a reset abandons the previous stream. */
export function useSurvey(): Survey {
  const [survey, dispatch] = useReducer(surveyReducer, initialSurvey);
  const controller = useRef<AbortController | null>(null);

  const start = useCallback((run: RunRequest) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
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
        if (controller.current === abort) controller.current = null;
      }
    })();
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

  return { survey, start, reset, toggleGap };
}
