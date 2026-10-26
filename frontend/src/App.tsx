import { useCallback, useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import type { PlaceHit, RunRequest, Verdict, Walk } from "./api/types";
import { BlockSection } from "./components/BlockSection";
import { Brief } from "./components/Brief";
import { ConceptsSection } from "./components/ConceptsSection";
import { DesignSheet, type DesignTarget } from "./components/DesignSheet";
import { ExampleBanner } from "./components/ExampleBanner";
import { ExampleWait } from "./components/ExampleWait";
import { GapsSection } from "./components/GapsSection";
import { ImproveSection } from "./components/ImproveSection";
import { KeepSurveys } from "./components/KeepSurveys";
import { Link } from "./components/Link";
import { LiveStatus } from "./components/LiveStatus";
import { NextStep } from "./components/NextStep";
import { SectionBoundary } from "./components/SectionBoundary";
import { SiteHeader, type TitleField } from "./components/SiteHeader";
import { SurveyLog } from "./components/SurveyLog";
import { panelId, TabPager, TabPanel, Tabs } from "./components/Tabs";
import { TasteSection } from "./components/TasteSection";
import { TopBar } from "./components/TopBar";
import { VerdictSection } from "./components/VerdictSection";
import { areaLabel, areaOf, walkLabel, type Area } from "./lib/area";
import { markState } from "./lib/brand";
import { DROPPED_PIN, siteName, unnamed } from "./lib/fullmap";
import { fmtLat, fmtLon, VERDICT_STAMPS } from "./lib/format";
import { firstResult, focusHeading, revealPanel } from "./lib/journey";
import { scrollBehavior, Settled, withViewTransition } from "./lib/motion";
import { homeMove, NavigateContext, type Navigate, type Showing } from "./lib/navigation";
import {
  BRIEF_URL,
  currentAddress,
  currentRoute,
  isPage,
  onBriefUrl,
  PRIVACY_URL,
  samePage,
  surveyUrl,
  type PageRoute,
  type SurveyRoute,
} from "./lib/routes";
import { posterButtonId } from "./lib/sections";
import { answerTab, hashTab, openingTab, surveyTabs, tabNo, type SurveyTab } from "./lib/surveyTabs";
import { shownTab } from "./lib/tabs";
import type { MapPoint } from "./map/controller";
import { areaWord } from "./map/pins";
import { SurveyMap, type PlacedSpot } from "./map/SurveyMap";
import { PageView } from "./pages/PageView";
import {
  askedLine,
  briefArea,
  briefOf,
  catchmentLines,
  formArea,
  initialBrief,
  missing,
  runRequest,
  unitLine,
  type BriefForm,
} from "./state/brief";
import { RUN_GONE } from "./state/record";
import { engine } from "./state/engine";
import { surveyExample, useExamples } from "./state/examples";
import { session } from "./state/session";
import { samePoint, usePinAddress, useSiteWalk, withAddress, type Site } from "./state/site";
import { surveyProgress, type SurveyState } from "./state/survey";
import { ThemeContext, useTheme } from "./state/theme";
import { useSurvey, type RestoreResult } from "./state/useSurvey";

/** The site as the survey view names it, fixed when the survey starts. */
interface Surveyed {
  label: string;
  eyebrow: string;
  fields: TitleField[];
}

/** A survey started here, with the site and the area it surveys: the brief may move on to another site while it runs. */
interface Started extends Surveyed {
  site: Site;
  area: Area;
}

/** What the window shows: the brief, a survey's link while it loads, the survey in memory, or another page. */
type Screen = { name: "brief" } | { name: "opening"; id: string } | { name: "survey" } | { name: "page"; route: PageRoute };

/** The concept whose design sheet is open. */
interface OpenSheet {
  runId: string;
  index: number;
  /** Where focus returns when the sheet closes; null for a sheet opened from a link. */
  opener: HTMLElement | null;
}

const NOTES_SHOWN = 60;
const EYEBROWS = { explore: "Site under survey", open: "Idea under test", improve: "Place under review" } as const;

/**
 * Four fields, like a drawing's title block; the unit rides under the constraints. The catchment names the area in the
 * server's words once it is traced (`walk`), its size, and the age focus ("For 25–34").
 */
function briefFields(run: RunRequest, walk: Walk | null, place: PlaceHit | null): TitleField[] {
  const notes = run.notes.length > NOTES_SHOWN ? `${run.notes.slice(0, NOTES_SHOWN - 1).trimEnd()}…` : run.notes;
  const asked = askedLine(run, place);
  const unit = unitLine(run);
  return [
    { label: "Coordinates", lines: [fmtLat(run.lat), fmtLon(run.lon)], mono: true },
    { label: "Catchment", lines: catchmentLines(run, walk) },
    { label: asked.label, lines: [asked.line] },
    run.intent === "improve"
      ? { label: "Compared with", lines: ["The places people here love in its category"] }
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

/** The survey's tabs and their panels share this prefix in their ids. */
const TABS_ID = "survey";

/** A restored survey's title block, rebuilt from the brief its run recorded, as the live one would have read. */
function recordedTitle(survey: SurveyState): Surveyed {
  if (!survey.site) return { label: "Survey in progress", eyebrow: EYEBROWS[survey.intent], fields: [] };
  const brief = briefOf(survey.site, survey.place);
  const run = runRequest(brief.site, brief.form);
  const name = siteName(brief.site);
  const label = run.intent === "improve" ? (survey.place?.name ?? name) : name;
  const fields = briefFields(run, survey.catchment, brief.form.place);
  return { label, eyebrow: EYEBROWS[run.intent], fields };
}

/** A survey's link starts on its loading screen; the other pages show themselves; every other address shows the brief. */
function firstScreen(): Screen {
  const route = currentRoute();
  if (route.page === "survey") return { name: "opening", id: route.id };
  return isPage(route) ? { name: "page", route } : { name: "brief" };
}

const linkedSheet = (route: SurveyRoute): OpenSheet | null =>
  route.sheet === null ? null : { runId: route.id, index: route.sheet, opener: null };

export function App() {
  const { theme, toggleTheme } = useTheme();
  const [screen, setScreen] = useState<Screen>(firstScreen);
  /** The survey sheet and its map, mounted once first needed and then kept, hidden, while another page shows. */
  const [stageOn, setStageOn] = useState(() => !isPage(currentRoute()));
  const [started, setStarted] = useState<Started | null>(null);
  const [site, setSite] = useState<Site | null>(null);
  const [form, setForm] = useState<BriefForm>(initialBrief);
  const [sheet, setSheet] = useState<OpenSheet | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  /** The survey on screen was restored or brought back rather than streamed here, so nothing on it animates in again. */
  const [settled, setSettled] = useState(false);
  /**
   * Counts fresh starts: each one draws a new brief, its search box empty, and a new map, with no pin, where a reload of
   * the page would have opened them.
   */
  const [mapEpoch, setMapEpoch] = useState(0);
  /** The map fills the screen: the bar and the sheet under it are inert meanwhile. */
  const [mapFull, setMapFull] = useState(false);
  /** Counts "Use this spot" on the full-screen map; the brief brings its next step into view and focus each time. */
  const [reveal, setReveal] = useState(0);
  /** The survey's tab, for the run it was chosen in: a survey opens on its log while it runs, else on its answer. */
  const [tab, setTab] = useState<{ run: number; id: SurveyTab } | null>(null);
  /** The tabs left since they were last shown: what they hold does not slide in again when they come back. */
  const [left, setLeft] = useState<{ run: number; tabs: SurveyTab[] }>({ run: 0, tabs: [] });
  /** The run whose answer the owner has opened since it completed: the status bar stops offering it. */
  const [answered, setAnswered] = useState<number | null>(null);
  /** The address last shown, to tell Back and Forward from a section link, which moves only the hash. */
  const address = useRef<string | null>(null);
  const focusTitle = useRef(false);
  const briefTrace = useSiteWalk(site, briefArea(form));
  const briefWalk = briefTrace.phase === "shown" ? briefTrace.walk : null;
  const { survey, start, restore, reset, toggleGap } = useSurvey();
  const examples = useExamples();

  const title = started ?? (survey.recorded === null ? null : recordedTitle(survey));
  const surveying = screen.name === "survey" && title !== null;
  const tabs = surveyTabs(survey);
  // A survey that appears opens on the tab its link names, else its log while it runs, else its answer; after that only
  // the owner changes tab.
  if (surveying && tab?.run !== survey.run) setTab({ run: survey.run, id: openingTab(survey, window.location.hash) });
  const selected = (shownTab(tabs, tab?.run === survey.run ? tab.id : null) ?? "log") as SurveyTab;
  const answer = survey.status === "complete" ? answerTab(survey) : null;
  if (surveying && answer !== null && selected === answer && answered !== survey.run) setAnswered(survey.run);
  const result = answer !== null && answered !== survey.run ? firstResult(survey) : null;
  const openGap = survey.openGap === null ? null : (survey.gaps?.[survey.openGap] ?? null);
  const surveySite: MapPoint | null = started?.site ?? survey.site;
  const surveyWalk = survey.catchment ?? (started && samePoint(started.site, site) ? briefWalk : null);
  /** The area the survey asked for: as started here, or as its record holds it (an older survey's is a walk). */
  const surveyArea: Area = started?.area ?? areaOf(survey.site ?? {});
  /** The area inside a sentence, in the server's words once traced ("30-minute drive"), else as asked. */
  const surveyAreaLabel = survey.catchment ? walkLabel(survey.catchment) : areaLabel(surveyArea);
  /** The area after "inside" or "outside": "the walk", or "the drive" for a drive or a road distance. */
  const surveyAreaWord = areaWord(survey.catchment?.travel ?? surveyArea.travel);
  const sheetConcept = surveying && sheet?.runId === survey.runId ? survey.concepts?.concepts?.[sheet.index] : undefined;
  const design: DesignTarget | null = sheet && sheetConcept ? { ...sheet, concept: sheetConcept } : null;
  const showing: Showing = surveying ? "survey" : screen.name === "opening" ? "opening" : screen.name === "page" ? "page" : "brief";
  /** The map grows to fill the screen on the brief, and from its dock beside a survey. */
  const expandable = showing === "brief" || showing === "survey";
  const pageInert = mapFull && expandable;
  /** The survey shown, or loading from its link, when it is one of the finished examples: it says so above it. */
  const example = surveyExample(
    examples.list,
    screen.name === "opening" ? screen.id : surveying ? survey.runId : null,
  );
  /** The examples' link in the bar: until they load, and for good once there are some. */
  const noExamples = examples.phase === "ready" && !examples.list.length;

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
    // Nothing waits for a dropped pin's address: without it yet, the survey goes by the pin's coordinates.
    const run = runRequest({ ...site, label: siteName(site) }, form);
    const fields = briefFields(run, briefWalk, form.place);
    const label = run.intent === "improve" ? (form.place?.name ?? run.label) : run.label;
    withViewTransition(() => {
      flushSync(() => {
        setStarted({ label, eyebrow: EYEBROWS[run.intent], fields, site, area: areaOf(run) });
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

  /** Back to the brief, which keeps the site and settings; `reveal` brings its next step into view and focus too. */
  function toBrief(reveal: boolean) {
    withViewTransition(() => {
      flushSync(() => {
        adoptBrief();
        reset();
        setStarted(null);
        setSheet(null);
        setScreen({ name: "brief" });
        if (reveal) setReveal((count) => count + 1);
      });
    });
    if (!onBriefUrl()) navigate(BRIEF_URL);
    if (!reveal) window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  function newSurvey() {
    toBrief(false);
  }

  /** "Back to the brief" from a survey that stopped: the brief as it was, its button in view and in focus to try again. */
  function retry() {
    toBrief(true);
  }

  /**
   * A fresh brief and map at "/", as a reload of "/" gave, without the reload. A survey in memory stays saved at its
   * link, which Back returns to; one still running goes on without this page.
   */
  function freshBrief() {
    withViewTransition(() => {
      flushSync(() => {
        reset();
        setStarted(null);
        setSheet(null);
        setNotice(null);
        setSettled(false);
        setSite(null);
        setForm(initialBrief);
        setScreen({ name: "brief" });
        setStageOn(true);
        setMapEpoch((epoch) => epoch + 1);
        setMapFull(false);
        setReveal(0);
      });
    });
    if (!onBriefUrl()) navigate(BRIEF_URL);
    window.scrollTo({ top: 0 });
  }

  /** The mark from a survey: a fresh brief, said aloud. */
  function startOver() {
    freshBrief();
    announce("Started over. The survey stays saved at its link.");
  }

  /** "Survey your own storefront", from the examples page and an example's banner: a fresh brief, its search empty. */
  function surveyOwn() {
    freshBrief();
    announce("A new survey: search for your storefront, or place it on the map.");
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
    if (now === address.current) {
      // Only the hash moved, to a tab's name (#gaps): the survey shows that tab when it has it.
      const asked = hashTab(window.location.hash);
      if (surveying && asked && asked !== selected && tabs.some((item) => item.id === asked && !item.disabled)) {
        showTab(asked, false);
      }
      return;
    }
    address.current = now;
    const route = currentRoute();
    // Another page starts at its top; the same page with only its query changed keeps its place.
    const toTop = isPage(route) ? !(screen.name === "page" && samePage(screen.route, route)) : screen.name === "page";
    flushSync(() => {
      setNotice(null);
      if (isPage(route)) {
        // As on the brief, a link still loading is abandoned and a survey stays in memory for Back.
        if (screen.name === "opening") reset();
        if (screen.name === "survey") adoptBrief();
        setScreen({ name: "page", route });
        setSheet(null);
        return;
      }
      setStageOn(true);
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
    if (toTop) window.scrollTo({ top: 0 });
  });

  /** In-app links and the pages' own moves: the address changes and the app follows it as it follows Back. */
  const go = useCallback<Navigate>((url, options) => {
    const next = new URL(url, window.location.href);
    const target = `${next.pathname}${next.search}${next.hash}`;
    if (!options?.replace && target === `${currentAddress()}${window.location.hash}`) return;
    if (options?.replace) window.history.replaceState(null, "", target);
    else window.history.pushState(null, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  /** The mark, clicked or tapped: the brief, in place (lib/navigation.ts says which way). */
  function goHome() {
    const move = homeMove(showing);
    if (move === "fresh") {
      startOver();
      return;
    }
    if (move === "brief") {
      go(BRIEF_URL);
      return;
    }
    // Already on the brief: back to its top with the form as it is. A brief shown at another address, such as a survey
    // link that is gone, takes "/" and drops its notice.
    if (!onBriefUrl()) {
      setNotice(null);
      navigate(BRIEF_URL, true);
    }
    window.scrollTo({ top: 0, behavior: scrollBehavior() });
  }

  const openFirstLink = useEffectEvent(() => {
    address.current = currentAddress();
    const route = currentRoute();
    if (route.page === "survey") openLink(route);
  });

  useEffect(() => {
    // The engine first: a nap shows its note before any other request starts waiting on it.
    engine.start();
    openFirstLink();
    void session.load();
    // Settings that gave up while the engine would not wake load as soon as it does.
    let was = engine.get().phase;
    const unwatch = engine.subscribe(() => {
      const phase = engine.get().phase;
      if (phase === "ready" && was !== "ready" && session.get().phase === "failed") void session.load();
      was = phase;
    });
    const onPopState = () => {
      followHistory();
    };
    window.addEventListener("popstate", onPopState);
    return () => {
      unwatch();
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
    // A sheet opened from a link has no poster it was opened from: focus goes to its poster's button instead, on the
    // concepts' tab.
    if (closing.opener) return;
    if (selected !== "concepts") showTab("concepts", false);
    document.getElementById(posterButtonId(closing.index))?.focus();
  }

  /**
   * Shows a tab of the survey and names it in the address (#concepts), so its link opens on it. When the page had
   * scrolled past the panel's top, it comes back into view under the pinned bars; `focus` moves focus to its heading.
   */
  function showTab(id: SurveyTab, focus: boolean) {
    const from = selected;
    flushSync(() => {
      setTab({ run: survey.run, id });
      if (from !== id) {
        setLeft((now) => ({ run: survey.run, tabs: [...(now.run === survey.run ? now.tabs : []), from] }));
      }
    });
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}#${id}`);
    const panel = document.getElementById(panelId(TABS_ID, id));
    const bar = document.querySelector<HTMLElement>(".survey-tabs");
    if (!panel) return;
    if (bar) revealPanel(panel, bar);
    if (focus) focusHeading(panel);
  }

  /** What a tab of the survey holds, once it has arrived. */
  function panelContent(id: SurveyTab): ReactNode {
    const no = tabNo(survey.intent, id);
    switch (id) {
      case "log":
        return (
          <SectionBoundary key={`log-${survey.run}`} label="The survey log">
            <SurveyLog no={no} log={survey.log} summary={survey.summary} />
          </SectionBoundary>
        );
      case "area":
        return survey.block ? (
          <SectionBoundary key={`block-${survey.run}`} label="The block">
            <BlockSection no={no} block={survey.block} area={surveyAreaLabel} />
          </SectionBoundary>
        ) : null;
      case "gaps":
        return survey.gaps ? (
          <SectionBoundary key={`gaps-${survey.run}`} label="The gaps">
            <GapsSection no={no} gaps={survey.gaps} openGap={survey.openGap} onToggle={toggleGap} area={surveyAreaWord} />
          </SectionBoundary>
        ) : null;
      case "verdict":
        return survey.verdict ? (
          <SectionBoundary key={`verdict-${survey.run}`} label="The verdict">
            <VerdictSection no={no} verdict={survey.verdict} />
          </SectionBoundary>
        ) : null;
      case "improve":
        return survey.improve ? (
          <SectionBoundary key={`improve-${survey.run}`} label="What to change">
            <ImproveSection no={no} data={survey.improve} />
          </SectionBoundary>
        ) : null;
      case "concepts":
        return survey.concepts ? (
          <SectionBoundary key={`concepts-${survey.run}`} label="The concepts">
            <ConceptsSection
              no={no}
              data={survey.concepts}
              rules={survey.understood}
              baseline={survey.baseline}
              onOpen={openDesign}
            />
          </SectionBoundary>
        ) : null;
      case "taste":
        return survey.taste ? (
          <SectionBoundary key={`taste-${survey.run}`} label="The wider taste">
            <TasteSection no={no} taste={survey.taste} cues={survey.cues ?? []} />
          </SectionBoundary>
        ) : null;
    }
  }

  /** A spot placed on the map: by hand, or found by the full-screen map's search, which knows the place's name. */
  function pickFromMap({ lat, lon, label }: PlacedSpot) {
    chooseSite({ id: null, label: label ?? DROPPED_PIN, lat, lon });
  }

  // A pin placed by hand takes its address once it comes, if it has not moved since: the brief, the search box and the
  // survey's header then name it, and a survey started from it sends it. A survey already started from the pin keeps
  // the coordinates it was sent with, and its header shows the address.
  usePinAddress(site, (pin, address) => {
    setSite((now) => withAddress(now, pin, address));
    setStarted((now) => (now && samePoint(now.site, pin) && unnamed(now.label) ? { ...now, label: address } : now));
  });

  const page = screen.name === "page" ? screen.route : null;

  return (
    <ThemeContext value={theme}>
      <NavigateContext value={go}>
        <TopBar
          mark={markState(surveying, survey.status)}
          progress={surveyProgress(survey)}
          home={homeMove(showing)}
          onHome={goHome}
          theme={theme}
          onToggleTheme={toggleTheme}
          inert={pageInert}
          examples={noExamples ? null : page?.page === "examples" ? "current" : "link"}
        />
        {page ? <PageView route={page} onFresh={surveyOwn} /> : null}
        {stageOn ? (
          <main className="stage" data-mode={surveying ? "survey" : "brief"} hidden={page !== null}>
            <article className="sheet" data-settled={surveying && settled ? "" : undefined} inert={pageInert}>
              <Brief
                key={mapEpoch}
                hidden={surveying || screen.name === "opening"}
                notice={notice}
                site={site}
                trace={briefTrace}
                reveal={reveal}
                form={form}
                onForm={patchForm}
                onSite={chooseSite}
                onPlace={choosePlace}
                onSurvey={startSurvey}
              />
              {example && (screen.name === "opening" || surveying) ? (
                <ExampleBanner example={example} onFresh={surveyOwn} />
              ) : null}
              {screen.name === "opening" ? (
                <section className="sec opening" aria-busy="true">
                  <p className="mono">Opening survey {screen.id}</p>
                </section>
              ) : null}
              {surveying ? (
                <Settled value={settled}>
                  <SectionBoundary key={`live-${survey.run}`} label="The survey status">
                    <LiveStatus
                      survey={survey}
                      result={result}
                      onResult={() => {
                        if (answer) showTab(answer, true);
                      }}
                      onRetry={retry}
                    />
                  </SectionBoundary>
                  {noExamples ? null : <ExampleWait key={`wait-${survey.run}`} running={survey.status === "running"} />}
                  <SiteHeader
                    eyebrow={title.eyebrow}
                    label={title.label}
                    fields={withVerdict(withUnderstood(title.fields, survey.understood), survey.verdict)}
                    point={surveySite}
                    onNewSurvey={newSurvey}
                    titleRef={titleRef}
                  />
                  <Tabs
                    label="Results"
                    items={tabs}
                    selected={selected}
                    onSelect={(id) => {
                      showTab(id as SurveyTab, false);
                    }}
                    idPrefix={TABS_ID}
                    pin="page"
                    className="survey-tabs"
                  />
                  {tabs.map(({ id }) => (
                    <TabPanel
                      key={id}
                      idPrefix={TABS_ID}
                      id={id}
                      selected={id === selected}
                      className={left.run === survey.run && left.tabs.includes(id) ? "tab-left" : undefined}
                    >
                      {panelContent(id)}
                      <TabPager
                        items={tabs}
                        current={id}
                        onSelect={(next) => {
                          showTab(next as SurveyTab, true);
                        }}
                      />
                    </TabPanel>
                  ))}
                </Settled>
              ) : null}
              {surveying && started !== null && survey.status === "complete" ? <KeepSurveys /> : null}
              <footer className="sheet-foot mono">
                <p>
                  Taste data by{" "}
                  <a href="https://www.qloo.com" target="_blank" rel="noopener">
                    Qloo
                  </a>
                  : aggregated and anonymized, and thinner in less digitally active areas. Read it as evidence for a decision,
                  not a forecast.
                </p>
                <p>
                  Built for the Qloo Agentic Hackathon. <Link href={PRIVACY_URL}>Privacy</Link>
                </p>
              </footer>
            </article>
            <SurveyMap
              key={mapEpoch}
              theme={theme}
              site={surveying ? surveySite : site}
              label={surveying ? null : (site?.label ?? null)}
              walk={surveying ? surveyWalk : briefWalk}
              trace={briefTrace}
              area={surveying ? surveyArea : formArea(form)}
              surveying={surveying}
              run={surveying ? survey.run : 0}
              streaming={surveying && survey.streaming}
              places={surveying ? (survey.block?.places ?? null) : null}
              gap={surveying ? openGap : null}
              gapsReady={surveying && (survey.gaps?.length ?? 0) > 0}
              expandable={expandable}
              onPick={pickFromMap}
              onExpand={setMapFull}
              onUse={() => {
                setReveal((count) => count + 1);
              }}
            />
            <NextStep
              site={site}
              active={showing === "brief" && !mapFull}
              onUse={() => {
                setReveal((count) => count + 1);
              }}
            />
          </main>
        ) : null}
        <DesignSheet target={design} onClose={closeDesign} />
        <p className="sr-only" role="status">
          {announcement}
        </p>
      </NavigateContext>
    </ThemeContext>
  );
}
