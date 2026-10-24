import { useEffect, useState } from "react";
import type { DonePayload } from "../api/types";
import { cssVars } from "../lib/css";
import { queriesText } from "../lib/format";
import { firstResult, goToSection, stickyTop, stoppedNext, type ResultLink } from "../lib/journey";
import type { SectionId } from "../lib/sections";
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

/** Where a section is from the owner's place on the page: on screen under the bars, below it or above it. */
type Place = "here" | "below" | "above";

/**
 * Where the section is, once first measured (null until then, so an action for a section already on screen never
 * flashes); "here" for good once the owner has had it on screen, scrolled there or sent there.
 */
function useSectionPlace(id: SectionId | null): Place | null {
  const [seen, setSeen] = useState<{ id: SectionId; place: Place } | null>(null);

  useEffect(() => {
    if (!id) return;
    const section = document.getElementById(id);
    if (!section) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        const top = entry.rootBounds?.top ?? 0;
        const place: Place = entry.isIntersecting ? "here" : entry.boundingClientRect.bottom <= top ? "above" : "below";
        setSeen({ id, place });
        if (place === "here") observer.disconnect();
      },
      // Under the sticky bars, and above the bottom fifth of the window: a section's first lines peeking in are not it.
      { rootMargin: `-${stickyTop()}px 0px -20% 0px` },
    );
    observer.observe(section);
    return () => {
      observer.disconnect();
    };
  }, [id]);

  return seen?.id === id ? seen.place : null;
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

/** The one thing to do once the survey is complete: go to the result it was asked for, named for it. */
function GoToResult({ result, place }: { result: ResultLink; place: Exclude<Place, "here"> }) {
  return (
    <button
      className="live-go"
      type="button"
      onClick={() => {
        goToSection(result.id);
      }}
    >
      {result.label}
      <span aria-hidden="true">{place === "above" ? "↑" : "↓"}</span>
    </button>
  );
}

interface LiveStatusProps {
  survey: SurveyState;
  /** Back to the brief, which keeps the site and settings the survey ran with: offered once a survey has stopped. */
  onRetry: () => void;
}

/**
 * Pinned under the top bar while a survey runs. Once complete it says so in one line, offers the way to the result the
 * owner asked for until they get there, and can be dismissed; once stopped it says why and leads back to the brief.
 */
export function LiveStatus({ survey, onRetry }: LiveStatusProps) {
  const [dismissed, setDismissed] = useState(false);
  const running = survey.status === "running";
  const failed = survey.status === "failed";
  const elapsed = useElapsed(survey.startedAt, running);
  const result = survey.status === "complete" ? firstResult(survey) : null;
  const place = useSectionPlace(result?.id ?? null);
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
        <div className="live-end">
          {result && place && place !== "here" ? <GoToResult result={result} place={place} /> : null}
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
