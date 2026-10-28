import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ahead,
  ApiError,
  ENGINE_ASLEEP,
  fetchAwake,
  fetched,
  fromEdge,
  isWaking,
  probeEngine,
  request,
  retryAfterMs,
  runPath,
  WAKE_BUDGET_MS,
  watchEngine,
  type WakeDeps,
} from "./client";

const NAP = { detail: "The survey engine is waking up; after a quiet spell that takes up to a minute.", waking: true };

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

/** The front door's answer while the backend wakes. */
const napping = (retryAfter = "3") => json(NAP, 503, { "retry-after": retryAfter });

/** Answers in turn, then napping for ever; a clock that moves only when the code under test sleeps. */
function fakeDeps(...answers: Response[]) {
  let now = 0;
  const slept: number[] = [];
  const deps: WakeDeps = {
    fetch: vi.fn(() => Promise.resolve(answers.shift() ?? napping())),
    now: () => now,
    sleep: vi.fn((ms: number, signal?: AbortSignal | null) => {
      if (signal?.aborted) return Promise.resolve(false);
      slept.push(ms);
      now += ms;
      return Promise.resolve(true);
    }),
  };
  return { deps, slept, elapsed: () => now };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("retryAfterMs", () => {
  const after = (value?: string) =>
    new Response(null, { status: 503, headers: value === undefined ? {} : { "retry-after": value } });

  it("reads seconds or a date, and keeps the wait between 1 and 15 seconds", () => {
    expect(retryAfterMs(after("3"))).toBe(3000);
    expect(retryAfterMs(after("1.5"))).toBe(1500);
    expect(retryAfterMs(after("0"))).toBe(1000);
    expect(retryAfterMs(after("600"))).toBe(15_000);
    const now = Date.UTC(2026, 9, 22, 12, 0, 0);
    expect(retryAfterMs(after(new Date(now + 5000).toUTCString()), now)).toBe(5000);
  });

  it("waits 3 seconds when the answer gives no usable Retry-After", () => {
    expect(retryAfterMs(after())).toBe(3000);
    expect(retryAfterMs(after("soon"))).toBe(3000);
  });
});

describe("isWaking", () => {
  it("is the front door's 503 that says waking, and nothing else", async () => {
    expect(await isWaking(napping())).toBe(true);
    expect(await isWaking(json({ detail: "Google sign-in is unavailable right now." }, 503))).toBe(false);
    expect(await isWaking(new Response("<html>Service waking up</html>", { status: 503 }))).toBe(false);
    expect(await isWaking(json(NAP, 200))).toBe(false);
  });

  it("leaves the answer readable", async () => {
    const answer = napping();
    await isWaking(answer);
    expect(await answer.json()).toEqual(NAP);
  });
});

describe("fetchAwake", () => {
  it("asks again after each Retry-After while the engine naps, and returns its first real answer", async () => {
    const { deps, slept } = fakeDeps(napping("3"), napping("2"), json({ ok: true }));
    const answer = await fetchAwake("/api/presets", {}, deps);
    expect(answer.status).toBe(200);
    expect(await answer.json()).toEqual({ ok: true });
    expect(slept).toEqual([3000, 2000]);
    expect(deps.fetch).toHaveBeenCalledTimes(3);
  });

  it("passes every other answer through at once, errors included", async () => {
    const { deps, slept } = fakeDeps(json({ detail: "Sign in first." }, 401), json({ detail: "Busy" }, 503));
    expect((await fetchAwake("/api/me/places", {}, deps)).status).toBe(401);
    expect((await fetchAwake("/api/auth/google", {}, deps)).status).toBe(503);
    expect(slept).toEqual([]);
  });

  it("gives up after two minutes in all, and says so in plain words", async () => {
    const watcher = { asking: vi.fn(), answered: vi.fn(), waking: vi.fn() };
    const stop = watchEngine(watcher);
    try {
      const { deps, elapsed, slept } = fakeDeps();
      const failure = await fetchAwake("/api/config", {}, deps).catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(ApiError);
      expect(failure).toMatchObject({ status: 503, message: ENGINE_ASLEEP, explained: true });
      expect(elapsed()).toBeLessThanOrEqual(WAKE_BUDGET_MS);
      expect(elapsed()).toBeGreaterThan(WAKE_BUDGET_MS - 3000);
      // Only the answers it waited after told the engine: the one it gave up on did not wake the note again.
      expect(watcher.waking).toHaveBeenCalledTimes(slept.length);
    } finally {
      stop();
    }
  });

  it("stops waiting once its request is abandoned", async () => {
    const { deps } = fakeDeps(napping());
    const abort = new AbortController();
    abort.abort();
    await expect(fetchAwake("/api/runs/r1", { signal: abort.signal }, deps)).rejects.toMatchObject({ name: "AbortError" });
    expect(deps.fetch).toHaveBeenCalledTimes(1);
  });

  it("tells the engine's watcher as it asks, as the engine naps and when the backend answers", async () => {
    const watcher = { asking: vi.fn(), answered: vi.fn(), waking: vi.fn() };
    const stop = watchEngine(watcher);
    try {
      await fetchAwake("/api/me", {}, fakeDeps(napping(), json({ user: null })).deps);
      expect(watcher.asking).toHaveBeenCalledTimes(1);
      expect(watcher.waking).toHaveBeenCalledTimes(1);
      expect(watcher.answered).toHaveBeenCalledTimes(1);
      // A server error is no sign of life: the backend's own 5xx, or a proxy's.
      await fetchAwake("/api/health", {}, fakeDeps(json({ detail: "Oops" }, 500)).deps);
      expect(watcher.answered).toHaveBeenCalledTimes(1);
    } finally {
      stop();
    }
  });

  it("does not take a copy the edge kept for the backend's answer", async () => {
    const watcher = { asking: vi.fn(), answered: vi.fn(), waking: vi.fn() };
    const stop = watchEngine(watcher);
    try {
      const kept = (cache: string) => json({ id: "ex" }, 200, { "x-walkin-cache": cache });
      await fetchAwake("/api/runs/ex", {}, fakeDeps(kept("hit")).deps);
      await fetchAwake("/api/runs/ex", {}, fakeDeps(kept("stale")).deps);
      expect(watcher.answered).not.toHaveBeenCalled();
      await fetchAwake("/api/runs/ex", {}, fakeDeps(kept("miss")).deps);
      await fetchAwake("/api/me", {}, fakeDeps(kept("bypass")).deps);
      expect(watcher.answered).toHaveBeenCalledTimes(2);
    } finally {
      stop();
    }
  });
});

describe("fromEdge", () => {
  it("is an answer the front door gave from a copy it keeps", () => {
    const answer = (cache?: string) => json({}, 200, cache ? { "x-walkin-cache": cache } : {});
    expect(fromEdge(answer("hit"))).toBe(true);
    expect(fromEdge(answer("stale"))).toBe(true);
    expect(fromEdge(answer("miss"))).toBe(false);
    expect(fromEdge(answer("bypass"))).toBe(false);
    expect(fromEdge(answer())).toBe(false);
  });
});

describe("request", () => {
  it("sleeps through a nap, then reads the answer", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValueOnce(napping("3")).mockResolvedValueOnce(json([{ id: "ues" }]));
    vi.stubGlobal("fetch", fetchMock);
    const answer = request<{ id: string }[]>("/api/presets");
    await vi.advanceTimersByTimeAsync(2999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(answer).resolves.toEqual([{ id: "ues" }]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("turns any other failure into an ApiError in the server's words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Sign in first." }, 401)));
    await expect(request("/api/me/places")).rejects.toMatchObject({ status: 401, message: "Sign in first." });
  });
});

describe("answers fetched ahead", () => {
  // `ahead` is the app's one cache: each test reads paths of its own.
  it("opens a finished survey from the one answer fetched ahead, then from memory", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ id: "a1", status: "complete", events: [] }));
    vi.stubGlobal("fetch", fetchMock);
    ahead.prefetch(runPath("a1"));
    ahead.prefetch(runPath("a1"));
    await expect(fetched(runPath("a1"))).resolves.toMatchObject({ id: "a1", status: "complete" });
    await expect(fetched(runPath("a1"))).resolves.toMatchObject({ id: "a1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("takes a 404 fetched ahead as the server's last word, without asking again", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ detail: "Not found." }, 404));
    vi.stubGlobal("fetch", fetchMock);
    ahead.prefetch(runPath("gone"));
    await expect(fetched(runPath("gone"))).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("asks again, in full, when the early ask met the engine napping", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(napping()).mockResolvedValueOnce(json({ id: "nap", status: "complete" }));
    vi.stubGlobal("fetch", fetchMock);
    ahead.prefetch(runPath("nap"));
    await expect(fetched(runPath("nap"))).resolves.toMatchObject({ id: "nap" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("asks the server when nothing was fetched ahead, and stops at once when the view goes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ id: "cold", status: "complete" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetched(runPath("cold"))).resolves.toMatchObject({ id: "cold" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    ahead.prefetch(runPath("left"));
    const view = new AbortController();
    view.abort();
    await expect(fetched(runPath("left"), view.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("probeEngine", () => {
  const probe = (answer: Response | Error) =>
    probeEngine(new AbortController().signal, {
      fetch: () => (answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer)),
    });

  it("tells an awake engine from a napping one and from no answer at all", async () => {
    expect(await probe(json({ ok: true }))).toBe("ready");
    expect(await probe(napping())).toBe("waking");
    expect(await probe(new Response("Bad gateway", { status: 502 }))).toBe("down");
    expect(await probe(new TypeError("Failed to fetch"))).toBe("down");
  });
});
