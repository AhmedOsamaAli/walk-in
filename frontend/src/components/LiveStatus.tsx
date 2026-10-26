import { useEffect, useState } from "react";
import type { DonePayload } from "../api/types";
import { cssVars } from "../lib/css";
import { queriesText } from "../lib/format";
import { stoppedNext, type ResultLink } from "../lib/journey";
import { useSurveyTitle } from "../lib/useSurveyTitle";
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

/**
 * The bar's height as the page's --live-h, so the tabs pin right under it and section jumps clear it, whatever it holds:
 * one line once complete, two while running, the reason in full once stopped. Gone with the bar.
 */
function measureBar(bar: HTMLElement | null): (() => void) | undefined {
  if (!bar) return;
  const root = document.documentElement;
  const observer = new ResizeObserver(() => {
    root.style.setProperty("--live-h", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
  });
  observer.observe(bar);
  return () => {
    observer.disconnect();
    root.style.removeProperty("--live-h");
  };
}

const seconds = (value: number) => (value < 10 ? value.toFixed(1) : Math.round(value).toString());

/** The finished survey in one line; a narrow screen drops the Qloo query count, and the time beside an action. */
function Summary({ summary }: { summary: DonePayload | null }) {
  if (!summary) return <>Survey complete</>;
  return (
    <>
      Survey complete<span className="live-secs"> · {seconds(summary.seconds)} s</span>
      <span className="live-extra"> · {queriesText(summary)}</span>
    </>
  );
}

interface LiveStatusProps {
  survey: SurveyState;
  /** The result the owner asked for, while they have not opened its tab yet; null once they have, or while it runs. */
  result: ResultLink | null;
  /** Opens the result's tab and moves focus to its heading. */
  onResult: () => void;
  /** Back to the brief, which keeps the site and settings the survey ran with: offered once a survey has stopped. */
  onRetry: () => void;
}

/**
 * Pinned under the top bar while a survey runs. Once complete it says so in one line, offers the result the owner asked
 * for until they open it, and can be dismissed; once stopped it says why and leads back to the brief.
 */
export function LiveStatus({ survey, result, onResult, onRetry }: LiveStatusProps) {
  const [dismissed, setDismissed] = useState(false);
  const running = survey.status === "running";
  const failed = survey.status === "failed";
  const elapsed = useElapsed(survey.startedAt, running);
  useSurveyTitle(survey.status);
  if (dismissed || survey.status === "idle") return null;

  const progress = surveyProgress(survey);
  const headline = running ? (
    (currentStep(survey)?.label ?? "Starting the survey")
  ) : survey.status === "complete" ? (
    <Summary summary={survey.summary} />
  ) : (
    `Survey stopped · ${survey.error ?? "unknown error"}`
  );
  const mark = survey.status === "complete" ? "✓" : failed ? "✕" : null;
  const found = survey.block !== null || survey.gaps !== null;

  return (
    <section ref={measureBar} className="live-status" data-state={survey.status} aria-label="Survey status">
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
        <div className="live-end">
          {result && survey.status === "complete" ? (
            <button className="live-go" type="button" onClick={onResult}>
              {result.label}
              <span aria-hidden="true">→</span>
            </button>
          ) : null}
          {failed ? (
            <button className="live-go" type="button" onClick={onRetry}>
              Back to the brief
            </button>
          ) : null}
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
        </div>
      )}
      <div className="live-more" aria-hidden={!running && !failed}>
        <div>
          {failed ? (
            <p className="live-note live-next" aria-live="polite">
              {stoppedNext(found)}
            </p>
          ) : (
            <p className="live-note" aria-live="polite">
              <b className="mono">Latest</b>
              {survey.latest ?? "Waiting for the first finding"}
            </p>
          )}
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
