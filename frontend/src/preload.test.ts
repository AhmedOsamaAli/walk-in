import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { needsOf, preloadLink, preloadRoute, preloadWhenIdle, routeOf } from "./preload";

const spies = vi.hoisted(() => ({
  prefetch: vi.fn(),
  chunks: {
    map: vi.fn(),
    survey: vi.fn(),
    kit: vi.fn(),
    examples: vi.fn(),
    places: vi.fn(),
    privacy: vi.fn(),
    founders: vi.fn(),
  },
}));

vi.mock("./chunks", () => ({
  mapChunk: { preload: spies.chunks.map },
  surveyChunk: { preload: spies.chunks.survey },
  kitChunk: { preload: spies.chunks.kit },
  examplesChunk: { preload: spies.chunks.examples },
  placesChunk: { preload: spies.chunks.places },
  privacyChunk: { preload: spies.chunks.privacy },
  foundersChunk: { preload: spies.chunks.founders },
}));

vi.mock("./api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/client")>()),
  ahead: { prefetch: spies.prefetch, take: vi.fn() },
}));

const BASE = "https://walkin.test/examples";
const TOKEN = "Av7v5rcNyjXToUQ9JyFkEyHFEHJ_jijsedhKYeMtO4E";

/** A browser with this connection, its page loaded or not, and no requestIdleCallback (timers stand in). */
function browser({ saveData = false, effectiveType = "4g", loaded = true } = {}) {
  const listeners = new Map<string, () => void>();
  vi.stubGlobal("window", {
    location: { href: BASE },
    setTimeout: (run: () => void, ms: number) => setTimeout(run, ms),
    clearTimeout: (timer: ReturnType<typeof setTimeout>) => {
      clearTimeout(timer);
    },
    addEventListener: (name: string, run: () => void) => listeners.set(name, run),
    removeEventListener: (name: string) => listeners.delete(name),
  });
  vi.stubGlobal("document", { readyState: loaded ? "complete" : "loading" });
  vi.stubGlobal("navigator", { connection: { saveData, effectiveType } });
  return { load: () => listeners.get("load")?.() };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("what an address needs", () => {
  it("names the chunks that draw each page and the answer it shows", () => {
    expect(needsOf({ page: "brief" })).toEqual({ chunks: ["map"], data: null });
    expect(needsOf({ page: "survey", id: "099134cbfaec", sheet: null })).toEqual({
      chunks: ["survey", "map"],
      data: "/api/runs/099134cbfaec",
    });
    expect(needsOf({ page: "kit", token: TOKEN })).toEqual({ chunks: ["kit"], data: `/api/kits/${TOKEN}` });
    expect(needsOf({ page: "dossier", token: TOKEN })).toEqual({ chunks: ["kit"], data: `/api/kits/${TOKEN}` });
    expect(needsOf({ page: "examples" })).toEqual({ chunks: ["examples"], data: null });
    expect(needsOf({ page: "places" })).toEqual({ chunks: ["places"], data: null });
    expect(needsOf({ page: "privacy" })).toEqual({ chunks: ["privacy"], data: null });
    // Founders' pages: their code only, since a campaign's answer depends on who asks and changes with every pledge.
    expect(needsOf({ page: "founders" })).toEqual({ chunks: ["founders"], data: null });
    expect(needsOf({ page: "campaign", id: "c4f1e2", pledge: null, cancelled: false })).toEqual({ chunks: ["founders"], data: null });
  });

  it("reads a link's route, and none for a link that leaves the app", () => {
    expect(routeOf("/s/099134cbfaec?sheet=1", BASE)).toEqual({ page: "survey", id: "099134cbfaec", sheet: 1 });
    expect(routeOf(`https://walkin.test/k/${TOKEN}/dossier`, BASE)).toEqual({ page: "dossier", token: TOKEN });
    expect(routeOf("https://www.qloo.com/", BASE)).toBeNull();
    expect(routeOf("http://[", BASE)).toBeNull();
  });
});

describe("preloading", () => {
  it("starts an address's chunks and its answer, or its answer alone", () => {
    preloadRoute({ page: "survey", id: "ex1", sheet: null });
    expect(spies.chunks.survey).toHaveBeenCalledTimes(1);
    expect(spies.chunks.map).toHaveBeenCalledTimes(1);
    expect(spies.prefetch).toHaveBeenCalledWith("/api/runs/ex1");
    vi.clearAllMocks();
    preloadRoute({ page: "kit", token: TOKEN }, { code: false });
    expect(spies.chunks.kit).not.toHaveBeenCalled();
    expect(spies.prefetch).toHaveBeenCalledWith(`/api/kits/${TOKEN}`);
  });

  it("starts nothing for a link out of the app, and only code for a page with no answer to fetch", () => {
    browser();
    preloadLink("https://www.qloo.com/");
    expect(spies.prefetch).not.toHaveBeenCalled();
    preloadLink("/privacy");
    expect(spies.chunks.privacy).toHaveBeenCalledTimes(1);
    expect(spies.prefetch).not.toHaveBeenCalled();
  });

  it("fetches a list's links once the page has loaded and the browser is idle", () => {
    const page = browser({ loaded: false });
    preloadWhenIdle(["/s/ex1", `/k/${TOKEN}`], { code: false });
    vi.advanceTimersByTime(5000);
    expect(spies.prefetch).not.toHaveBeenCalled();
    page.load();
    vi.advanceTimersByTime(500);
    expect(spies.prefetch.mock.calls).toEqual([["/api/runs/ex1"], [`/api/kits/${TOKEN}`]]);
    expect(spies.chunks.survey).not.toHaveBeenCalled();
  });

  it("can be called off before it starts", () => {
    browser();
    const cancel = preloadWhenIdle(["/s/ex1"]);
    cancel();
    vi.advanceTimersByTime(5000);
    expect(spies.prefetch).not.toHaveBeenCalled();
  });

  it("fetches nothing ahead for a visitor saving data or on a 2G connection", () => {
    browser({ saveData: true });
    preloadWhenIdle(["/s/ex1"]);
    browser({ effectiveType: "slow-2g" });
    preloadWhenIdle(["/s/ex2"]);
    vi.advanceTimersByTime(5000);
    expect(spies.prefetch).not.toHaveBeenCalled();
  });
});
