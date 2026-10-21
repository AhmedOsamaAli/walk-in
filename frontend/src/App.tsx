import { useState } from "react";
import { flushSync } from "react-dom";
import type { PlaceHit, RunRequest, Verdict } from "./api/types";
import { BlockSection } from "./components/BlockSection";
import { Brief } from "./components/Brief";
import { ConceptsSection } from "./components/ConceptsSection";
import { DesignSheet, type DesignTarget } from "./components/DesignSheet";
import { GapsSection } from "./components/GapsSection";
import { ImproveSection } from "./components/ImproveSection";
import { LiveStatus } from "./components/LiveStatus";
import { SectionBoundary } from "./components/SectionBoundary";
import { SiteHeader, type TitleField } from "./components/SiteHeader";
import { SurveyLog } from "./components/SurveyLog";
import { TasteSection } from "./components/TasteSection";
import { TopBar } from "./components/TopBar";
import { VerdictSection } from "./components/VerdictSection";
import { fmtLat, fmtLon, VERDICT_STAMPS } from "./lib/format";
import { scrollBehavior, withViewTransition } from "./lib/motion";
import { sectionNo, sectionsFor, useSectionSpy, type SectionId } from "./lib/sections";
import type { MapPoint } from "./map/controller";
import { SurveyMap } from "./map/SurveyMap";
import { askedLine, initialBrief, missing, runRequest, unitLine, type BriefForm } from "./state/brief";
import { useSiteWalk, type Site } from "./state/site";
import { surveyProgress, type SurveyState } from "./state/survey";
import { useTheme } from "./state/theme";
import { useSurvey } from "./state/useSurvey";

/** The site as the survey view names it, fixed when the survey starts. */
interface Surveyed {
  label: string;
  eyebrow: string;
  fields: TitleField[];
}

const NOTES_SHOWN = 60;
const EYEBROWS = { explore: "Site under survey", open: "Idea under test", improve: "Place under review" } as const;

/** Four fields, like a drawing's title block; the unit rides under the constraints. */
function briefFields(run: RunRequest, area: number | null, place: PlaceHit | null): TitleField[] {
  const notes = run.notes.length > NOTES_SHOWN ? `${run.notes.slice(0, NOTES_SHOWN - 1).trimEnd()}…` : run.notes;
  const asked = askedLine(run, place);
  const unit = unitLine(run);
  return [
    { label: "Coordinates", lines: [fmtLat(run.lat), fmtLon(run.lon)], mono: true },
    { label: "Catchment", lines: area == null ? [`${run.minutes}-min walk`] : [`${run.minutes}-min walk`, `${area} km²`] },
    { label: asked.label, lines: [asked.line] },
    run.intent === "improve"
      ? { label: "Compared with", lines: ["The places locals love in its category"] }
      : { label: "Constraints", lines: unit ? [notes || "None", unit] : [notes || "None"] },
  ];
}

/** Once the server has read the owner's notes, the title block shows the rules it applies rather than the raw text. */
function withUnderstood(fields: TitleField[], understood: string[]): TitleField[] {
  if (!understood.length) return fields;
  const rules = understood.map((rule) => rule.charAt(0).toUpperCase() + rule.slice(1)).join(" · ");
  return fields.map((field) => (field.label === "Constraints" ? { ...field, lines: [rules, ...field.lines.slice(1)] } : field));
}

/** The verdict on the owner's idea joins the idea in the title block, so the answer is at the top of the page. */
function withVerdict(fields: TitleField[], verdict: Verdict | null): TitleField[] {
  if (!verdict) return fields;
  return fields.map((field) =>
    field.label === "Your idea" ? { ...field, lines: [...field.lines, `Verdict: ${VERDICT_STAMPS[verdict.level]}`] } : field,
  );
}

function readySections(survey: SurveyState): SectionId[] {
  const ready: SectionId[] = ["s-log"];
  if (survey.block) ready.push("s-block");
  if (survey.gaps) ready.push("s-gaps");
  if (survey.verdict) ready.push("s-verdict");
  if (survey.improve) ready.push("s-improve");
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
  const [form, setForm] = useState<BriefForm>(initialBrief);
  const [design, setDesign] = useState<DesignTarget | null>(null);
  const briefWalk = useSiteWalk(site, form.minutes);
  const { survey, start, reset, toggleGap } = useSurvey();

  const surveying = surveyed !== null;
  const intent = surveying ? survey.intent : form.intent;
  const ready = surveying ? readySections(survey) : [];
  const current = useSectionSpy(ready);
  const openGap = survey.openGap === null ? null : (survey.gaps?.[survey.openGap] ?? null);

  function patchForm(patch: Partial<BriefForm>) {
    setForm((previous) => ({ ...previous, ...patch }));
  }

  /** A new site leaves the place picked for the old one behind. */
  function chooseSite(next: Site) {
    setSite(next);
    patchForm({ place: null });
  }

  /** Picking the owner's place moves the pin onto it. */
  function choosePlace(place: PlaceHit | null) {
    patchForm({ place });
    if (place) setSite({ id: null, label: place.name, lat: place.lat, lon: place.lon });
  }

  function startSurvey() {
    if (!site || survey.streaming || missing(site, form)) return;
    const run = runRequest(site, form);
    const fields = briefFields(run, briefWalk?.area_km2 ?? null, form.place);
    const label = run.intent === "improve" ? (form.place?.name ?? site.label) : site.label;
    withViewTransition(() => {
      flushSync(() => {
        setSurveyed({ label, eyebrow: EYEBROWS[run.intent], fields });
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
    chooseSite({ id: null, label: "Dropped pin", lat, lon });
  }

  return (
    <>
      <TopBar
        fill={markFill(survey, surveying)}
        sections={sectionsFor(intent)}
        ready={ready}
        current={current}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      <main className="stage" data-mode={surveying ? "survey" : "brief"}>
        <article className="sheet">
          <Brief
            hidden={surveying}
            site={site}
            walk={briefWalk}
            form={form}
            onForm={patchForm}
            onSite={chooseSite}
            onPlace={choosePlace}
            onSurvey={startSurvey}
          />
          {surveyed ? (
            <>
              <SectionBoundary key={`live-${survey.run}`} label="The survey status">
                <LiveStatus survey={survey} />
              </SectionBoundary>
              <SiteHeader
                eyebrow={surveyed.eyebrow}
                label={surveyed.label}
                fields={withVerdict(withUnderstood(surveyed.fields, survey.understood), survey.verdict)}
                onNewSurvey={newSurvey}
              />
              <SectionBoundary key={`log-${survey.run}`} label="The survey log">
                <SurveyLog log={survey.log} summary={survey.summary} />
              </SectionBoundary>
              {survey.block ? (
                <SectionBoundary key={`block-${survey.run}`} label="The block">
                  <BlockSection block={survey.block} />
                </SectionBoundary>
              ) : null}
              {survey.gaps ? (
                <SectionBoundary key={`gaps-${survey.run}`} label="The gaps">
                  <GapsSection gaps={survey.gaps} openGap={survey.openGap} onToggle={toggleGap} />
                </SectionBoundary>
              ) : null}
              {survey.verdict ? (
                <SectionBoundary key={`verdict-${survey.run}`} label="The verdict">
                  <VerdictSection no={sectionNo(intent, "s-verdict")} verdict={survey.verdict} />
                </SectionBoundary>
              ) : null}
              {survey.improve ? (
                <SectionBoundary key={`improve-${survey.run}`} label="What to change">
                  <ImproveSection no={sectionNo(intent, "s-improve")} data={survey.improve} />
                </SectionBoundary>
              ) : null}
              {survey.concepts ? (
                <SectionBoundary key={`concepts-${survey.run}`} label="The concepts">
                  <ConceptsSection
                    no={sectionNo(intent, "s-concepts")}
                    data={survey.concepts}
                    baseline={survey.baseline}
                    onOpen={openDesign}
                  />
                </SectionBoundary>
              ) : null}
              {survey.taste ? (
                <SectionBoundary key={`taste-${survey.run}`} label="The wider taste">
                  <TasteSection no={sectionNo(intent, "s-taste")} taste={survey.taste} cues={survey.cues ?? []} />
                </SectionBoundary>
              ) : null}
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
          minutes={form.minutes}
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
