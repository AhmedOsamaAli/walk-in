import { useEffect, useState } from "react";
import type { DonePayload } from "../api/types";
import { cssVars } from "../lib/css";
import { currentStep, surveyProgress, type SurveyState } from "../state/survey";

function useElapsed(startedAt: number, running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      setElapsed((performance.now() - startedAt) / 1000);
    }, 100);
    return () => {
      window.clearInterval(timer);
    };
  }, [startedAt, running]);
  return elapsed;
}

const seconds = (value: number) => (value < 10 ? value.toFixed(1) : Math.round(value).toString());

/** The finished survey in one line; the Qloo call count is the part a narrow screen drops. */
function Summary({ summary }: { summary: DonePayload | null }) {
  if (!summary) return <>Survey complete</>;
  const calls = `${summary.qloo_calls} Qloo ${summary.qloo_calls === 1 ? "call" : "calls"}`;
  const cached = summary.cache_hits ? ` · ${summary.cache_hits} from cache` : "";
  return (
    <>
      Survey complete · {seconds(summary.seconds)} s<span className="live-extra"> · {calls}{cached}</span>
    </>
  );
}

/** Pinned under the top bar while a survey runs; it collapses into a one-line summary that can be dismissed. */
export function LiveStatus({ survey }: { survey: SurveyState }) {
  const [dismissed, setDismissed] = useState(false);
  const running = survey.status === "running";
  const elapsed = useElapsed(survey.startedAt, running);
  if (dismissed || survey.status === "idle") return null;

  const progress = surveyProgress(survey);
  const headline = running ? (
    (currentStep(survey)?.label ?? "Starting the survey")
  ) : survey.status === "complete" ? (
    <Summary summary={survey.summary} />
  ) : (
    `Survey stopped · ${survey.error ?? "unknown error"}`
  );
  const mark = survey.status === "complete" ? "✓" : survey.status === "failed" ? "✕" : null;

  return (
    <section className="live" data-state={survey.status} aria-label="Survey status">
      <span className="live-mark" aria-hidden="true">
        {mark}
      </span>
      <p className="live-step" aria-live="polite" aria-atomic="true">
        {headline}
      </p>
      {running ? (
        <span className="live-time mono" role="timer">
          {seconds(elapsed)} s
        </span>
      ) : (
        <button
          className="live-close"
          type="button"
          onClick={() => {
            setDismissed(true);
          }}
          aria-label="Dismiss the survey summary"
          title="Dismiss"
        >
          ×
        </button>
      )}
      <div className="live-more" aria-hidden={!running}>
        <div>
          <p className="live-note" aria-live="polite">
            <b className="mono">Latest</b>
            {survey.latest ?? "Waiting for the first finding"}
          </p>
        </div>
      </div>
      <div
        className="live-track"
        role="progressbar"
        aria-label="Survey progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <i style={cssVars({ "--p": progress })} />
      </div>
    </section>
  );
}
