/* The app's router: what the address shows (the brief or a survey on the stage beside the map, or another page) and
   every move between them, by a link, by Back and Forward, or by the app's own buttons. A link changes the address and
   the app follows it, as it follows Back; the brief's and the survey's own moves (start, back to the brief, start over)
   say where they lead in the address too. The stage's layout is pages/Stage.tsx, the pages' pages/PageView.tsx. */
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { designChunk, surveyChunk } from "./chunks";
import { DesignSheet, type DesignTarget } from "./components/DesignSheet";
import { TopBar } from "./components/TopBar";
import { areaLabel, areaOf, walkLabel, type Area } from "./lib/area";
import { markState } from "./lib/brand";
import { DROPPED_PIN, siteName, unnamed } from "./lib/fullmap";
import { whenIdle } from "./lib/lazy";
import { scrollBehavior, withViewTransition } from "./lib/motion";
import { homeMove, NavigateContext, type Navigate, type Showing } from "./lib/navigation";
import { BRIEF_URL, currentAddress, currentRoute, isPage, onBriefUrl, samePage, surveyUrl, type SurveyRoute } from "./lib/routes";
import { posterButtonId } from "./lib/sections";
import { briefFields, EYEBROWS, recordedTitle } from "./lib/titleBlock";
import type { MapPoint } from "./map/controller";
import type { PlacedSpot } from "./map/SurveyMap";
import { PageView } from "./pages/PageView";
import { Stage } from "./pages/Stage";
import { briefOf, formArea, initialBrief, missing, runRequest } from "./state/brief";
import { engine } from "./state/engine";
import { surveyExample, useExamples } from "./state/examples";
import { RUN_GONE } from "./state/record";
import { firstScreen, linkedSheet, type OpenSheet, type Screen, type Started } from "./state/screen";
import { session } from "./state/session";
import { samePoint, usePinAddress, withAddress } from "./state/site";
import { surveyProgress } from "./state/survey";
import { ThemeContext, useTheme } from "./state/theme";
import { useBriefForm } from "./state/useBriefForm";
import { useSurvey, type RestoreResult } from "./state/useSurvey";
import { useSurveyTabs } from "./state/useSurveyTabs";

export function App() {
  const { theme, toggleTheme } = useTheme();
  const [screen, setScreen] = useState<Screen>(firstScreen);
  /** The survey sheet and its map, mounted once first needed and then kept, hidden, while another page shows. */
  const [stageOn, setStageOn] = useState(() => !isPage(currentRoute()));
  const [started, setStarted] = useState<Started | null>(null);
  const { site, form, trace: briefTrace, walk: briefWalk, setSite, setForm, patchForm, chooseSite, choosePlace } = useBriefForm();
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
  /** The address last shown, to tell Back and Forward from a section link, which moves only the hash. */
  const address = useRef<string | null>(null);
  const focusTitle = useRef(false);
  const { survey, start, restore, reset, toggleGap } = useSurvey();
  const examples = useExamples();

  const title = started ?? (survey.recorded === null ? null : recordedTitle(survey));
  const surveying = screen.name === "survey" && title !== null;
  const { tabs, selected, left, answer, result, showTab, followHash } = useSurveyTabs(survey, surveying);
  const openGap = survey.openGap === null ? null : (survey.gaps?.[survey.openGap] ?? null);
  const surveySite: MapPoint | null = started?.site ?? survey.site;
  const surveyWalk = survey.catchment ?? (started && samePoint(started.site, site) ? briefWalk : null);
  /** The area the survey asked for: as started here, or as its record holds it (an older survey's is a walk). */
  const surveyArea: Area = started?.area ?? areaOf(survey.site ?? {});
  /** The area inside a sentence, in the server's words once traced ("30-minute drive"), else as asked. */
  const surveyAreaLabel = survey.catchment ? walkLabel(survey.catchment) : areaLabel(surveyArea);
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
  const page = screen.name === "page" ? screen.route : null;

  const titleRef = useCallback((node: HTMLHeadingElement | null) => {
    if (!node || !focusTitle.current) return;
    focusTitle.current = false;
    node.focus({ preventScroll: true });
  }, []);

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

  /* ---------- The brief's and the survey's own moves ---------- */

  function startSurvey() {
    // While new surveys are paused, the brief offers the surveyed storefronts instead of its survey button.
    if (!site || surveying || missing(site, form) || session.get().config?.surveys_paused) return;
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

  /* ---------- A survey's link ---------- */

  /**
   * Shows a survey's recorded copy once it has loaded, or the brief with a notice when it cannot be shown. The survey's
   * view loads meanwhile, and the record waits for it, so the survey replaces the loading line in one go.
   */
  function openLink(route: SurveyRoute) {
    void restore(route.id, surveyChunk.load().catch(() => undefined)).then((result) => {
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

  /* ---------- The design sheet over a survey ---------- */

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

  // A link's design sheet that the run never produced leaves the address once the run has ended.
  const dropSheet = useEffectEvent((runId: string) => {
    replaceSheet(runId, null);
  });
  const lostSheet = sheet !== null && design === null && !survey.streaming && survey.runId === sheet.runId;
  useEffect(() => {
    if (lostSheet) dropSheet(sheet.runId);
  }, [lostSheet, sheet]);

  /* ---------- History: Back, Forward and the app's links ---------- */

  /**
   * Back and Forward: shows what the address now asks for. Each one commits at once, without a view transition to wait
   * for, so a Back pressed straight after another acts on the page this one left.
   */
  const followHistory = useEffectEvent(() => {
    const now = currentAddress();
    if (now === address.current) {
      // Only the hash moved, to a tab's name (#gaps): the survey shows that tab when it has it.
      followHash(window.location.hash);
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
    // Once the first screen is up, a survey's view loads too, so a survey started from the brief shows at once.
    const cancelIdle = isPage(currentRoute()) ? undefined : whenIdle(surveyChunk.preload);
    return () => {
      cancelIdle?.();
      unwatch();
      window.removeEventListener("popstate", onPopState);
    };
  }, []);

  // A survey on screen: its design sheets' code loads while the owner reads.
  useEffect(() => {
    if (!surveying) return;
    return whenIdle(designChunk.preload);
  }, [surveying]);

  // A survey started here gets its own address once the server names it, so Back returns to the brief.
  useEffect(() => {
    if (!surveying || survey.recorded !== null || !survey.runId) return;
    const route = currentRoute();
    if (route.page === "survey" && route.id === survey.runId) return;
    window.history.pushState(null, "", surveyUrl(survey.runId));
    address.current = currentAddress();
  }, [surveying, survey.recorded, survey.runId]);

  /* ---------- What shows ---------- */

  const revealBrief = () => {
    setReveal((count) => count + 1);
  };

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
          founders={page?.page === "founders" ? "current" : "link"}
        />
        {page ? <PageView route={page} onFresh={surveyOwn} /> : null}
        {stageOn ? (
          <Stage
            hidden={page !== null}
            surveying={surveying}
            settled={settled}
            inert={pageInert}
            epoch={mapEpoch}
            brief={{
              hidden: surveying || screen.name === "opening",
              notice,
              site,
              trace: briefTrace,
              reveal,
              form,
              onForm: patchForm,
              onSite: chooseSite,
              onPlace: choosePlace,
              onSurvey: startSurvey,
            }}
            example={screen.name === "opening" || surveying ? example : null}
            onFresh={surveyOwn}
            opening={screen.name === "opening" ? screen.id : null}
            survey={
              surveying
                ? {
                    survey,
                    title,
                    settled,
                    tabs,
                    selected,
                    left,
                    result,
                    answer,
                    examples: !noExamples,
                    keep: started !== null && survey.status === "complete",
                    point: surveySite,
                    areaLabel: surveyAreaLabel,
                    travel: survey.catchment?.travel ?? surveyArea.travel,
                    titleRef,
                    onShowTab: showTab,
                    onRetry: retry,
                    onNewSurvey: newSurvey,
                    onToggleGap: toggleGap,
                    onOpenDesign: openDesign,
                  }
                : null
            }
            map={{
              theme,
              site: surveying ? surveySite : site,
              label: surveying ? null : (site?.label ?? null),
              walk: surveying ? surveyWalk : briefWalk,
              trace: briefTrace,
              area: surveying ? surveyArea : formArea(form),
              surveying,
              run: surveying ? survey.run : 0,
              streaming: surveying && survey.streaming,
              places: surveying ? (survey.block?.places ?? null) : null,
              gap: surveying ? openGap : null,
              gapsReady: surveying && (survey.gaps?.length ?? 0) > 0,
              expandable,
              onPick: pickFromMap,
              onExpand: setMapFull,
              onUse: revealBrief,
            }}
            next={{ site, active: showing === "brief" && !mapFull, onUse: revealBrief }}
          />
        ) : null}
        <DesignSheet target={design} onClose={closeDesign} />
        <p className="sr-only" role="status">
          {announcement}
        </p>
      </NavigateContext>
    </ThemeContext>
  );
}
