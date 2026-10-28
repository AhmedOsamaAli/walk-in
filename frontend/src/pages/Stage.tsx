/* The brief and the survey, on their sheet beside the map: the brief, an example's banner, a survey's link while it
   loads, the survey itself and the sheet's foot; then the map, which docks beside a survey, and the phone's "Use this
   spot". The map (with Leaflet) and the survey's view load in chunks of their own, so the first screen paints before
   them; each holds its place meanwhile, so nothing moves when it arrives, and a chunk that will not load says so there. */
import { Suspense } from "react";
import type { Example } from "../api/types";
import { mapChunk, surveyChunk } from "../chunks";
import { Brief, type BriefProps } from "../components/Brief";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { ExampleBanner } from "../components/ExampleBanner";
import { Link } from "../components/Link";
import { NextStep, type NextStepProps } from "../components/NextStep";
import { SectionBoundary } from "../components/SectionBoundary";
import { lazyComponent } from "../lib/lazy";
import { PRIVACY_URL } from "../lib/routes";
import type { SurveyMapProps } from "../map/SurveyMap";
import type { SurveyViewProps } from "./SurveyView";

const SurveyMap = lazyComponent(mapChunk, (chunk) => chunk.SurveyMap);
const SurveyView = lazyComponent(surveyChunk, (chunk) => chunk.SurveyView);

/** The map's frame while its code loads: the same box, so nothing moves when the map arrives; or a note, if it will not. */
function MapFrame({ docked, failed = false }: { docked: boolean; failed?: boolean }) {
  return (
    <div className="map-frame" data-dock={docked ? "" : undefined} aria-hidden={failed ? undefined : true}>
      <div className="map-canvas" />
      {failed ? (
        <p className="map-failed" role="alert">
          The map could not load. Reload the page to try again.
        </p>
      ) : null}
    </div>
  );
}

/** A survey's link while it loads, and a survey while its view's code loads. */
function Opening({ id }: { id: string | null }) {
  return (
    <section className="sec opening" aria-busy="true">
      <p className="mono">{id ? `Opening survey ${id}` : "Opening the survey"}</p>
    </section>
  );
}

function SheetFoot() {
  return (
    <footer className="sheet-foot mono">
      <p>
        Taste data by{" "}
        <a href="https://www.qloo.com" target="_blank" rel="noopener">
          Qloo
        </a>
        : aggregated and anonymized, and thinner in less digitally active areas. Read it as evidence for a decision, not a
        forecast.
      </p>
      <p>
        Built for the Qloo Agentic Hackathon. <Link href={PRIVACY_URL}>Privacy</Link>
      </p>
    </footer>
  );
}

export interface StageProps {
  /** Another page shows: the stage stays, hidden, so a survey and the map keep their state for Back. */
  hidden: boolean;
  /** A survey shows rather than the brief. */
  surveying: boolean;
  /** The survey on screen was restored or brought back rather than streamed here: nothing on it animates in again. */
  settled: boolean;
  /** The map fills the screen: the sheet under it is inert meanwhile. */
  inert: boolean;
  /** Counts fresh starts: each draws a new brief, its search box empty, and a new map, with no pin. */
  epoch: number;
  brief: BriefProps;
  /** The finished example on screen, or loading from its link: it says so above it. */
  example: Example | null;
  /** "Survey your own storefront", from an example's banner. */
  onFresh: () => void;
  /** The survey whose link is loading. */
  opening: string | null;
  /** The survey on screen. */
  survey: SurveyViewProps | null;
  map: SurveyMapProps;
  next: NextStepProps;
}

export function Stage({ hidden, surveying, settled, inert, epoch, brief, example, onFresh, opening, survey, map, next }: StageProps) {
  return (
    <main className="stage" data-mode={surveying ? "survey" : "brief"} hidden={hidden}>
      <article className="sheet" data-settled={surveying && settled ? "" : undefined} inert={inert}>
        <Brief key={epoch} {...brief} />
        {example ? <ExampleBanner example={example} onFresh={onFresh} /> : null}
        {opening !== null ? <Opening id={opening} /> : null}
        {survey ? (
          <SectionBoundary key={`view-${survey.survey.run}`} label="The survey">
            <Suspense fallback={<Opening id={survey.survey.runId} />}>
              <SurveyView {...survey} />
            </Suspense>
          </SectionBoundary>
        ) : null}
        <SheetFoot />
      </article>
      <ErrorBoundary key={epoch} fallback={<MapFrame docked={map.surveying} failed />}>
        <Suspense fallback={<MapFrame docked={map.surveying} />}>
          <SurveyMap {...map} />
        </Suspense>
      </ErrorBoundary>
      <NextStep {...next} />
    </main>
  );
}
