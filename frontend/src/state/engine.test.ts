import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ENGINE_ASLEEP, sleep, WAKE_BUDGET_MS, type EngineProbe } from "../api/client";
import {
  createEngineStore,
  FADE_MS,
  FRESH_MS,
  NOTE_AFTER_MS,
  POLL_MS,
  PROBE_MS,
  READY_MS,
  type EngineDeps,
  type EngineNote,
} from "./engine";

/** A look at the engine that answers `outcome` after `ms`, or "down" as soon as it is cut short. */
function answering(outcome: EngineProbe, ms = 0) {
  return (signal: AbortSignal) =>
    new Promise<EngineProbe>((resolve) => {
      const timer = setTimeout(() => {
        resolve(outcome);
      }, ms);
      signal.addEventListener("abort", () => {
        clearTimeout(timer);
        resolve("down");
      });
    });
}

/** A look that never answers until it is cut short. */
const hanging = (signal: AbortSignal) =>
  new Promise<EngineProbe>((resolve) => {
    signal.addEventListener("abort", () => {
      resolve("down");
    });
  });

function store(probe: EngineDeps["probe"]) {
  const look = vi.fn(probe);
  const engine = createEngineStore({
    probe: look,
    now: () => Date.now(),
    sleep,
    later: (ms, run) => {
      const timer = setTimeout(run, ms);
      return () => {
        clearTimeout(timer);
      };
    },
  });
  const notes: EngineNote[] = [];
  engine.subscribe(() => {
    if (notes.at(-1) !== engine.get().note) notes.push(engine.get().note);
  });
  return { engine, look, notes };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the engine store", () => {
  it("says nothing when the engine answers quickly", async () => {
    const { engine, look, notes } = store(answering("ready", 300));
    engine.start();
    expect(engine.get().phase).toBe("checking");
    await vi.advanceTimersByTimeAsync(300);
    expect(engine.get()).toMatchObject({ phase: "ready", note: "none" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notes).toEqual(["none"]);
    expect(look).toHaveBeenCalledTimes(1);
  });

  it("shows the note once 1.5 s pass without an answer, then Ready, then lets it fade", async () => {
    const { engine, notes } = store(answering("ready", 10_000));
    engine.start();
    await vi.advanceTimersByTimeAsync(NOTE_AFTER_MS - 1);
    expect(engine.get().note).toBe("none");
    await vi.advanceTimersByTimeAsync(1);
    expect(engine.get()).toMatchObject({ phase: "waking", note: "waking", since: 0 });
    await vi.advanceTimersByTimeAsync(10_000 - NOTE_AFTER_MS);
    expect(engine.get()).toMatchObject({ phase: "ready", note: "ready" });
    await vi.advanceTimersByTimeAsync(READY_MS);
    expect(engine.get().note).toBe("leaving");
    await vi.advanceTimersByTimeAsync(FADE_MS);
    expect(engine.get().note).toBe("none");
    expect(notes).toEqual(["none", "waking", "ready", "leaving", "none"]);
  });

  it("shows the note at once when the front door says the engine naps, and asks every 2 s until it wakes", async () => {
    const outcomes: EngineProbe[] = ["waking", "waking", "waking", "ready"];
    const { engine, look } = store(() => Promise.resolve(outcomes.shift() ?? "ready"));
    engine.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(engine.get().note).toBe("waking");
    expect(look).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    expect(look).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(POLL_MS * 2);
    expect(look).toHaveBeenCalledTimes(4);
    expect(engine.get()).toMatchObject({ phase: "ready", note: "ready" });
  });

  it("cuts a look that hangs and sends the next one", async () => {
    const { engine, look } = store(hanging);
    engine.start();
    await vi.advanceTimersByTimeAsync(PROBE_MS);
    expect(look).toHaveBeenCalledTimes(1);
    expect(look.mock.calls[0]?.[0].aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    expect(look).toHaveBeenCalledTimes(2);
    expect(engine.get().note).toBe("waking");
  });

  it("gives up after two minutes, and Try again starts over", async () => {
    const { engine, look } = store(answering("waking"));
    engine.start();
    const waiting = engine.whenReady();
    const failed = expect(waiting).rejects.toThrow(ENGINE_ASLEEP);
    await vi.advanceTimersByTimeAsync(WAKE_BUDGET_MS);
    await failed;
    expect(engine.get()).toMatchObject({ phase: "asleep", note: "asleep" });
    expect(look.mock.calls.length).toBeLessThanOrEqual(WAKE_BUDGET_MS / POLL_MS);
    look.mockImplementation(answering("ready", 500));
    engine.retry();
    expect(engine.get()).toMatchObject({ phase: "waking", note: "waking", since: WAKE_BUDGET_MS });
    await vi.advanceTimersByTimeAsync(500);
    expect(engine.get()).toMatchObject({ phase: "ready", note: "ready" });
  });

  it("is ready at once when the engine answered lately, and looks again first after a quiet spell", async () => {
    const { engine, look } = store(answering("ready"));
    engine.start();
    await vi.advanceTimersByTimeAsync(0);
    await expect(engine.whenReady()).resolves.toBeUndefined();
    expect(look).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(FRESH_MS + 1);
    const ready = engine.whenReady();
    expect(engine.get().phase).toBe("checking");
    await vi.advanceTimersByTimeAsync(0);
    await expect(ready).resolves.toBeUndefined();
    expect(look).toHaveBeenCalledTimes(2);
  });

  it("waits for a nap to end before a survey starts, without failing it", async () => {
    // The front door says "waking" until the engine is up, 40 s in.
    const { engine } = store(() => Promise.resolve(Date.now() >= 40_000 ? "ready" : "waking"));
    const order: string[] = [];
    void engine.whenReady().then(() => order.push("survey starts"));
    await vi.advanceTimersByTimeAsync(39_999);
    expect(order).toEqual([]);
    expect(engine.get().note).toBe("waking");
    await vi.advanceTimersByTimeAsync(1);
    expect(order).toEqual(["survey starts"]);
  });

  it("lets go of a wait that is abandoned, and keeps looking for everyone else", async () => {
    const { engine } = store(hanging);
    engine.start();
    const abort = new AbortController();
    const waiting = engine.whenReady(abort.signal);
    abort.abort();
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
    expect(engine.get().phase).toBe("checking");
  });

  it("learns from other requests: an answer settles a wake at once, a napping answer shows the note", async () => {
    const { engine, look } = store(hanging);
    engine.start();
    engine.watcher.waking();
    expect(engine.get()).toMatchObject({ phase: "waking", note: "waking" });
    engine.watcher.answered();
    expect(engine.get()).toMatchObject({ phase: "ready", note: "ready" });
    await vi.advanceTimersByTimeAsync(PROBE_MS + POLL_MS);
    expect(look).toHaveBeenCalledTimes(1);
  });

  it("looks again when a request goes out after a quiet spell, and only then", async () => {
    const { engine, look } = store(answering("ready"));
    engine.start();
    await vi.advanceTimersByTimeAsync(0);
    engine.watcher.asking();
    expect(look).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(FRESH_MS + 1);
    engine.watcher.asking();
    expect(engine.get().phase).toBe("checking");
    await vi.advanceTimersByTimeAsync(0);
    expect(look).toHaveBeenCalledTimes(2);
    expect(engine.get()).toMatchObject({ phase: "ready", note: "none" });
  });
});
