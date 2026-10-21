import { useState } from "react";
import { flushSync } from "react-dom";
import type { Focus, RunRequest, WalkMinutes } from "./api/types";
import { BlockSection } from "./components/BlockSection";
import { Brief } from "./components/Brief";
import { ConceptsSection } from "./components/ConceptsSection";
import { DesignSheet, type DesignTarget } from "./components/DesignSheet";
import { GapsSection } from "./components/GapsSection";
import { LiveStatus } from "./components/LiveStatus";
import { SiteHeader, type TitleField } from "./components/SiteHeader";
import { SurveyLog } from "./components/SurveyLog";
import { TasteSection } from "./components/TasteSection";
import { TopBar } from "./components/TopBar";
import { FOCUS_LABELS, fmtLat, fmtLon } from "./lib/format";
import { scrollBehavior, withViewTransition } from "./lib/motion";
import { useSectionSpy, type SectionId } from "./lib/sections";
import type { MapPoint } from "./map/controller";
import { SurveyMap } from "./map/SurveyMap";
import { useSiteWalk, type Site } from "./state/site";
import { surveyProgress, type SurveyState } from "./state/survey";
import { useTheme } from "./state/theme";
import { useSurvey } from "./state/useSurvey";

/** The site as the survey view names it, fixed when the survey starts. */
interface Surveyed {
  label: string;
  fields: TitleField[];
}

const NOTES_SHOWN = 60;

function briefFields(site: Site, minutes: WalkMinutes, area: number | null, focus: Focus, notes: string): TitleField[] {
  const shortNotes = notes.length > NOTES_SHOWN ? `${notes.slice(0, NOTES_SHOWN - 1).trimEnd()}…` : notes;
  return [
    { label: "Coordinates", lines: [fmtLat(site.lat), fmtLon(site.lon)], mono: true },
    { label: "Catchment", lines: area == null ? [`${minutes}-min walk`] : [`${minutes}-min walk`, `${area} km²`] },
    { label: "Business", lines: [FOCUS_LABELS[focus]] },
    { label: "Constraints", lines: [shortNotes || "None"] },
  ];
}

function readySections(survey: SurveyState): SectionId[] {
  const ready: SectionId[] = ["s-log"];
  if (survey.block) ready.push("s-block");
  if (survey.gaps) ready.push("s-gaps");
  if (survey.concepts) ready.push("s-concepts");
  if (survey.taste) ready.push("s-taste");
  return ready;
}

/** The mark's square fills with the survey: a resting level on the brief, then the pipeline's progress. */
function markFill(survey: SurveyState, surveying: boolean): number {
  if (!surveying) return 0.42;
  return survey.status === "complete" ? 1 : Math.max(0.06, surveyProgress(survey));
}

export function App() {
  const { theme, toggleTheme } = useTheme();
  const [surveyed, setSurveyed] = useState<Surveyed | null>(null);
  const [site, setSite] = useState<Site | null>(null);
  const [minutes, setMinutes] = useState<WalkMinutes>(10);
  const [focus, setFocus] = useState<Focus>("any");
  const [notes, setNotes] = useState("");
  const [design, setDesign] = useState<DesignTarget | null>(null);
  const briefWalk = useSiteWalk(site, minutes);
  const { survey, start, reset, toggleGap } = useSurvey();

  const surveying = surveyed !== null;
  const ready = surveying ? readySections(survey) : [];
  const current = useSectionSpy(ready);
  const openGap = survey.openGap === null ? null : (survey.gaps?.[survey.openGap] ?? null);

  function startSurvey() {
    if (!site || survey.streaming) return;
    const run: RunRequest = { lat: site.lat, lon: site.lon, label: site.label, focus, notes: notes.trim(), minutes };
    const fields = briefFields(site, minutes, briefWalk?.area_km2 ?? null, focus, run.notes);
    withViewTransition(() => {
      flushSync(() => {
        setSurveyed({ label: site.label, fields });
        start(run);
      });
    });
    window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  function newSurvey() {
    withViewTransition(() => {
      flushSync(() => {
        reset();
        setSurveyed(null);
      });
    });
    window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  function openDesign(index: number, opener: HTMLElement | null) {
    const concept = survey.concepts?.concepts?.[index];
    if (concept && survey.runId) setDesign({ runId: survey.runId, index, concept, opener });
  }

  function pickFromMap({ lat, lon }: MapPoint) {
    setSite({ id: null, label: "Dropped pin", lat, lon });
  }

  return (
    <>
      <TopBar fill={markFill(survey, surveying)} ready={ready} current={current} theme={theme} onToggleTheme={toggleTheme} />
      <main className="stage" data-mode={surveying ? "survey" : "brief"}>
        <article className="sheet">
          <Brief
            hidden={surveying}
            site={site}
            walk={briefWalk}
            minutes={minutes}
            focus={focus}
            notes={notes}
            onSite={setSite}
            onMinutes={setMinutes}
            onFocus={setFocus}
            onNotes={setNotes}
            onSurvey={startSurvey}
          />
          {surveyed ? (
            <>
              <LiveStatus key={survey.run} survey={survey} />
              <SiteHeader label={surveyed.label} fields={surveyed.fields} onNewSurvey={newSurvey} />
              <SurveyLog log={survey.log} summary={survey.summary} />
              {survey.block ? <BlockSection block={survey.block} /> : null}
              {survey.gaps ? <GapsSection gaps={survey.gaps} openGap={survey.openGap} onToggle={toggleGap} /> : null}
              {survey.concepts ? (
                <ConceptsSection data={survey.concepts} baseline={survey.baseline} onOpen={openDesign} />
              ) : null}
              {survey.taste ? <TasteSection taste={survey.taste} cues={survey.cues ?? []} /> : null}
            </>
          ) : null}
          <footer className="sheet-foot mono">
            <p>
              Taste data reflects aggregated, anonymized behaviour and is thinner in less digitally active areas. Read it
              as evidence for a decision, not a forecast.
            </p>
            <p>Built for the Qloo Agentic Hackathon.</p>
          </footer>
        </article>
        <SurveyMap
          theme={theme}
          site={site}
          walk={survey.catchment ?? briefWalk}
          minutes={minutes}
          surveying={surveying}
          run={survey.run}
          streaming={survey.streaming}
          places={survey.block?.places ?? null}
          gap={openGap}
          onPick={pickFromMap}
        />
      </main>
      <DesignSheet
        target={design}
        onClose={() => {
          setDesign(null);
        }}
      />
    </>
  );
}
