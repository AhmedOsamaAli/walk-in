import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
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
import { markState } from "./lib/brand";
import { fmtLat, fmtLon, VERDICT_STAMPS } from "./lib/format";
import { scrollBehavior, Settled, withViewTransition } from "./lib/motion";
import { BRIEF_URL, currentAddress, currentRoute, onBriefUrl, surveyUrl, type SurveyRoute } from "./lib/routes";
import { posterButtonId, sectionNo, sectionsFor, useSectionSpy, type SectionId } from "./lib/sections";
import type { MapPoint } from "./map/controller";
import { SurveyMap } from "./map/SurveyMap";
import { askedLine, briefOf, initialBrief, missing, runRequest, unitLine, type BriefForm } from "./state/brief";
import { RUN_GONE } from "./state/record";
import { useSiteWalk, type Site } from "./state/site";
import { surveyProgress, type SurveyState } from "./state/survey";
import { useTheme } from "./state/theme";
import { useSurvey, type RestoreResult } from "./state/useSurvey";

/** The site as the survey view names it, fixed when the survey starts. */
interface Surveyed {
  label: string;
  eyebrow: string;
  fields: TitleField[];
}

/** A survey started here, with the site it surveys: the brief may move on to another site while it runs. */
interface Started extends Surveyed {
  site: Site;
}

/** What the sheet shows: the brief, a survey's link while it loads, or the survey in memory. */
type Screen = { name: "brief" } | { name: "opening"; id: string } | { name: "survey" };

/** The concept whose design sheet is open. */
interface OpenSheet {
  runId: string;
  index: number;
  /** Where focus returns when the sheet closes; null for a sheet opened from a link. */
  opener: HTMLElement | null;
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

/** A restored survey's title block, rebuilt from the brief its run recorded, as the live one would have read. */
function recordedTitle(survey: SurveyState): Surveyed {
  if (!survey.site) return { label: "Survey in progress", eyebrow: EYEBROWS[survey.intent], fields: [] };
  const brief = briefOf(survey.site, survey.place);
  const run = runRequest(brief.site, brief.form);
  const label = run.intent === "improve" ? (survey.place?.name ?? brief.site.label) : brief.site.label;
  const fields = briefFields(run, survey.catchment?.area_km2 ?? null, brief.form.place);
  return { label, eyebrow: EYEBROWS[run.intent], fields };
}

/** A survey's link starts on its loading screen; every other address shows the brief. */
function firstScreen(): Screen {
  const route = currentRoute();
  return route.page === "survey" ? { name: "opening", id: route.id } : { name: "brief" };
}

const linkedSheet = (route: SurveyRoute): OpenSheet | null =>
  route.sheet === null ? null : { runId: route.id, index: route.sheet, opener: null };

export function App() {
  const { theme, toggleTheme } = useTheme();
  const [screen, setScreen] = useState<Screen>(firstScreen);
  const [started, setStarted] = useState<Started | null>(null);
  const [site, setSite] = useState<Site | null>(null);
  const [form, setForm] = useState<BriefForm>(initialBrief);
  const [sheet, setSheet] = useState<OpenSheet | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  /** The survey on screen was restored or brought back rather than streamed here, so nothing on it animates in again. */
  const [settled, setSettled] = useState(false);
  /** The address last shown, to tell Back and Forward from a section link, which moves only the hash. */
  const address = useRef<string | null>(null);
  const focusTitle = useRef(false);
  const briefWalk = useSiteWalk(site, form.minutes);
  const { survey, start, restore, reset, toggleGap } = useSurvey();

  const title = started ?? (survey.recorded === null ? null : recordedTitle(survey));
  const surveying = screen.name === "survey" && title !== null;
  const intent = surveying ? survey.intent : form.intent;
  const ready = surveying ? readySections(survey) : [];
  const current = useSectionSpy(ready);
  const openGap = survey.openGap === null ? null : (survey.gaps?.[survey.openGap] ?? null);
  const surveySite: MapPoint | null = started?.site ?? survey.site;
  const surveyWalk = survey.catchment ?? (started?.site === site ? briefWalk : null);
  const sheetConcept = surveying && sheet?.runId === survey.runId ? survey.concepts?.concepts?.[sheet.index] : undefined;
  const design: DesignTarget | null = sheet && sheetConcept ? { ...sheet, concept: sheetConcept } : null;

  const titleRef = useCallback((node: HTMLHeadingElement | null) => {
    if (!node || !focusTitle.current) return;
    focusTitle.current = false;
    node.focus({ preventScroll: true });
  }, []);

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

  /** Says it in the status region; the same words twice in a row are still announced. */
  function announce(text: string) {
    setAnnouncement((previous) => (previous === text ? `${text}\u00a0` : text));
  }

  function navigate(url: string, replace = false) {
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    address.current = currentAddress();
  }

  /** Keeps the open design sheet in the survey's address, while the address is that survey's. */
  function replaceSheet(runId: string, index: number | null) {
    const route = currentRoute();
    if (route.page !== "survey" || route.id !== runId || route.sheet === index) return;
    navigate(`${surveyUrl(runId, index)}${window.location.hash}`, true);
  }

  /** A brief without a site of its own takes the restored survey's site and settings, so it can be run again. */
  function adoptBrief() {
    if (site || !survey.site || survey.recorded === null) return;
    const brief = briefOf(survey.site, survey.place);
    setSite(brief.site);
    setForm(brief.form);
  }

  function startSurvey() {
    if (!site || surveying || missing(site, form)) return;
    const run = runRequest(site, form);
    const fields = briefFields(run, briefWalk?.area_km2 ?? null, form.place);
    const label = run.intent === "improve" ? (form.place?.name ?? site.label) : site.label;
    withViewTransition(() => {
      flushSync(() => {
        setStarted({ label, eyebrow: EYEBROWS[run.intent], fields, site });
        setScreen({ name: "survey" });
        setSettled(false);
        setSheet(null);
        setNotice(null);
        start(run);
      });
    });
    // A brief shown at another address (a survey that is gone, a page still to come) starts over from "/".
    if (!onBriefUrl()) navigate(BRIEF_URL, true);
    window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  function newSurvey() {
    withViewTransition(() => {
      flushSync(() => {
        adoptBrief();
        reset();
        setStarted(null);
        setSheet(null);
        setScreen({ name: "brief" });
      });
    });
    if (!onBriefUrl()) navigate(BRIEF_URL);
    window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  /** Shows a survey's recorded copy once it has loaded, or the brief with a notice when it cannot be shown. */
  function openLink(route: SurveyRoute) {
    void restore(route.id).then((result) => {
      land(route, result);
    });
  }

  function land(route: SurveyRoute, result: RestoreResult) {
    if (result.outcome === "superseded") return;
    flushSync(() => {
      if (result.outcome === "shown") {
        focusTitle.current = true;
        setScreen({ name: "survey" });
        setSettled(true);
        setSheet(linkedSheet(route));
        announce("Survey restored");
        return;
      }
      const message = result.outcome === "missing" ? RUN_GONE : `This survey could not be loaded. ${result.message}`;
      setScreen({ name: "brief" });
      setNotice(message);
      announce(message);
    });
  }

  /**
   * Back and Forward: shows what the address now asks for. Each one commits at once, without a view transition to wait
   * for, so a Back pressed straight after another acts on the page this one left.
   */
  const followHistory = useEffectEvent(() => {
    const now = currentAddress();
    if (now === address.current) return;
    address.current = now;
    const route = currentRoute();
    flushSync(() => {
      setNotice(null);
      if (route.page === "brief") {
        // A link still loading is abandoned; a survey stays in memory, still streaming if it was, for Forward.
        if (screen.name === "opening") reset();
        if (screen.name === "survey") adoptBrief();
        setScreen({ name: "brief" });
        setSheet(null);
        return;
      }
      const inMemory = title !== null && survey.runId === route.id;
      if (inMemory && surveying) {
        setSheet(route.sheet === (sheet?.index ?? null) ? sheet : linkedSheet(route));
        return;
      }
      if (inMemory) {
        focusTitle.current = true;
        setScreen({ name: "survey" });
        setSettled(true);
        setSheet(linkedSheet(route));
        announce("Survey restored");
        return;
      }
      setStarted(null);
      setSheet(null);
      setScreen({ name: "opening", id: route.id });
      openLink(route);
    });
  });

  const openFirstLink = useEffectEvent(() => {
    address.current = currentAddress();
    const route = currentRoute();
    if (route.page === "survey") openLink(route);
  });

  useEffect(() => {
    openFirstLink();
    const onPopState = () => {
      followHistory();
    };
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
    };
  }, []);

  // A survey started here gets its own address once the server names it, so Back returns to the brief.
  useEffect(() => {
    if (!surveying || survey.recorded !== null || !survey.runId) return;
    const route = currentRoute();
    if (route.page === "survey" && route.id === survey.runId) return;
    window.history.pushState(null, "", surveyUrl(survey.runId));
    address.current = currentAddress();
  }, [surveying, survey.recorded, survey.runId]);

  // A link's design sheet that the run never produced leaves the address once the run has ended.
  const dropSheet = useEffectEvent((runId: string) => {
    replaceSheet(runId, null);
  });
  const lostSheet = sheet !== null && design === null && !survey.streaming && survey.runId === sheet.runId;
  useEffect(() => {
    if (lostSheet) dropSheet(sheet.runId);
  }, [lostSheet, sheet]);

  function openDesign(index: number, opener: HTMLElement | null) {
    const runId = survey.runId;
    if (!runId || !survey.concepts?.concepts?.[index]) return;
    setSheet({ runId, index, opener });
    replaceSheet(runId, index);
  }

  function closeDesign() {
    const closing = sheet;
    setSheet(null);
    if (!closing) return;
    replaceSheet(closing.runId, null);
    // A sheet opened from a link has no poster it was opened from: focus goes to its poster's button instead.
    if (!closing.opener) document.getElementById(posterButtonId(closing.index))?.focus();
  }

  function pickFromMap({ lat, lon }: MapPoint) {
    chooseSite({ id: null, label: "Dropped pin", lat, lon });
  }

  return (
    <>
      <TopBar
        mark={markState(surveying, survey.status)}
        progress={surveyProgress(survey)}
        sections={sectionsFor(intent)}
        ready={ready}
        current={current}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      <main className="stage" data-mode={surveying ? "survey" : "brief"}>
        <article className="sheet" data-settled={surveying && settled ? "" : undefined}>
          <Brief
            hidden={surveying || screen.name === "opening"}
            notice={notice}
            site={site}
            walk={briefWalk}
            form={form}
            onForm={patchForm}
            onSite={chooseSite}
            onPlace={choosePlace}
            onSurvey={startSurvey}
          />
          {screen.name === "opening" ? (
            <section className="sec opening" aria-busy="true">
              <p className="mono">Opening survey {screen.id}</p>
            </section>
          ) : null}
          {surveying ? (
            <Settled value={settled}>
              <SectionBoundary key={`live-${survey.run}`} label="The survey status">
                <LiveStatus survey={survey} />
              </SectionBoundary>
              <SiteHeader
                eyebrow={title.eyebrow}
                label={title.label}
                fields={withVerdict(withUnderstood(title.fields, survey.understood), survey.verdict)}
                onNewSurvey={newSurvey}
                titleRef={titleRef}
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
            </Settled>
          ) : null}
          <footer className="sheet-foot mono">
            <p>
              Taste data by{" "}
              <a href="https://www.qloo.com" target="_blank" rel="noopener">
                Qloo
              </a>
              : aggregated and anonymized, and thinner in less digitally active areas. Read it as evidence for a decision,
              not a forecast.
            </p>
            <p>Built for the Qloo Agentic Hackathon.</p>
          </footer>
        </article>
        <SurveyMap
          theme={theme}
          site={surveying ? surveySite : site}
          walk={surveying ? surveyWalk : briefWalk}
          minutes={surveying ? (survey.site?.minutes ?? form.minutes) : form.minutes}
          surveying={surveying}
          run={surveying ? survey.run : 0}
          streaming={surveying && survey.streaming}
          places={surveying ? (survey.block?.places ?? null) : null}
          gap={surveying ? openGap : null}
          onPick={pickFromMap}
        />
      </main>
      <DesignSheet target={design} onClose={closeDesign} />
      <p className="sr-only" role="status">
        {announcement}
      </p>
    </>
  );
}
