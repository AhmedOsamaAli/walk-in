import { afterEach, describe, expect, it, vi } from "vitest";
import { lazyModule, reloadForChunk, whenIdle } from "./lazy";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a module loaded on first use", () => {
  it("loads once however often it is asked for, and says what it has", async () => {
    const importer = vi.fn(() => Promise.resolve({ name: "map" }));
    const chunk = lazyModule(importer);
    expect(chunk.current()).toBeNull();
    chunk.preload();
    const [a, b] = await Promise.all([chunk.load(), chunk.load()]);
    expect(a).toBe(b);
    expect(importer).toHaveBeenCalledTimes(1);
    expect(chunk.current()).toEqual({ name: "map" });
  });

  it("tries again after a load that failed, and a preload's failure is left to whoever renders it", async () => {
    const importer = vi
      .fn<() => Promise<{ name: string }>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ name: "map" });
    const chunk = lazyModule(importer);
    chunk.preload();
    await expect(chunk.load()).rejects.toThrow("offline");
    expect(chunk.current()).toBeNull();
    await expect(chunk.load()).resolves.toEqual({ name: "map" });
    expect(importer).toHaveBeenCalledTimes(2);
  });
});

describe("a chunk that will not load", () => {
  function memory(start: Record<string, string> = {}) {
    const items = new Map(Object.entries(start));
    return {
      getItem: (key: string) => items.get(key) ?? null,
      setItem: (key: string, value: string) => {
        items.set(key, value);
      },
    };
  }

  it("reloads the page onto the newest build, never twice within a minute", () => {
    const storage = memory();
    const reload = vi.fn();
    expect(reloadForChunk(storage, 1_000_000, reload)).toBe(true);
    expect(reloadForChunk(storage, 1_030_000, reload)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(reloadForChunk(storage, 1_061_000, reload)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("does not reload when it cannot remember having reloaded, which could loop", () => {
    const reload = vi.fn();
    const broken = {
      getItem: () => null,
      setItem: () => {
        throw new Error("storage is full");
      },
    };
    expect(reloadForChunk(broken, 1_000_000, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("when the browser is idle", () => {
  it("runs the work in an idle moment, at the latest after the timeout, and can be called off", () => {
    const requestIdleCallback = vi.fn((work: () => void, options: { timeout: number }) => {
      expect(options.timeout).toBe(3000);
      work();
      return 7;
    });
    const cancelIdleCallback = vi.fn();
    vi.stubGlobal("window", { requestIdleCallback, cancelIdleCallback });
    const work = vi.fn();
    const cancel = whenIdle(work);
    expect(work).toHaveBeenCalledTimes(1);
    cancel();
    expect(cancelIdleCallback).toHaveBeenCalledWith(7);
  });

  it("waits half a second instead where the browser has no idle callbacks", () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {
      setTimeout: (run: () => void, ms: number) => setTimeout(run, ms),
      clearTimeout: (timer: ReturnType<typeof setTimeout>) => {
        clearTimeout(timer);
      },
    });
    const work = vi.fn();
    whenIdle(work);
    vi.advanceTimersByTime(499);
    expect(work).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(work).toHaveBeenCalledTimes(1);
    const later = vi.fn();
    whenIdle(later)();
    vi.advanceTimersByTime(1000);
    expect(later).not.toHaveBeenCalled();
  });
});
