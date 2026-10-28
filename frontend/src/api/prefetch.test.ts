import { describe, expect, it, vi } from "vitest";
import { createPrefetchCache, PREFETCH_MAX, PREFETCH_TTL_MS, settled, type PrefetchDeps } from "./prefetch";

/** A fetch whose answers the test settles by hand, a clock it moves, and the cache under test. */
function harness(keep: PrefetchDeps["keep"] = () => true) {
  let now = 0;
  const pending = new Map<string, { resolve: (body: unknown) => void; reject: (error: Error) => void }>();
  const fetch = vi.fn(
    (path: string) =>
      new Promise<unknown>((resolve, reject) => {
        pending.set(path, { resolve, reject });
      }),
  );
  const cache = createPrefetchCache({ fetch, keep, now: () => now });
  return {
    cache,
    fetch,
    answer: async (path: string, body: unknown) => {
      pending.get(path)?.resolve(body);
      await Promise.resolve();
      await Promise.resolve();
    },
    fail: async (path: string) => {
      pending.get(path)?.reject(new Error("offline"));
      await Promise.resolve();
      await Promise.resolve();
    },
    tick: (ms: number) => {
      now += ms;
    },
  };
}

const RUN = "/api/runs/ex1";

describe("the answers fetched ahead", () => {
  it("asks once for a path however often it is fetched ahead, and hands that answer to the view that opens it", async () => {
    const { cache, fetch, answer } = harness();
    cache.prefetch(RUN);
    cache.prefetch(RUN);
    const taken = cache.take(RUN);
    expect(fetch).toHaveBeenCalledTimes(1);
    await answer(RUN, { status: "complete" });
    await expect(taken).resolves.toEqual({ status: "complete" });
    // Kept: a second view of it, or another prefetch, asks nothing more.
    cache.prefetch(RUN);
    await expect(cache.take(RUN)).resolves.toEqual({ status: "complete" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("has nothing for a path no one fetched ahead", () => {
    const { cache } = harness();
    expect(cache.take(RUN)).toBeNull();
  });

  it("hands an answer still on its way to the view, then forgets it when it may still change", async () => {
    const { cache, fetch, answer } = harness(() => false);
    cache.prefetch(RUN);
    const taken = cache.take(RUN);
    expect(taken).not.toBeNull();
    await answer(RUN, { status: "running" });
    await expect(taken).resolves.toEqual({ status: "running" });
    expect(cache.take(RUN)).toBeNull();
    cache.prefetch(RUN);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("forgets a failed ask, so the view asks the server itself", async () => {
    const { cache, fail } = harness();
    cache.prefetch(RUN);
    const taken = cache.take(RUN);
    await fail(RUN);
    await expect(taken).rejects.toThrow("offline");
    expect(cache.take(RUN)).toBeNull();
  });

  it("keeps an answer for a minute, then asks again", async () => {
    const { cache, fetch, answer, tick } = harness();
    cache.prefetch(RUN);
    await answer(RUN, { status: "complete" });
    tick(PREFETCH_TTL_MS);
    expect(cache.take(RUN)).not.toBeNull();
    tick(1);
    expect(cache.take(RUN)).toBeNull();
    cache.prefetch(RUN);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps at most PREFETCH_MAX answers, letting the oldest go first", () => {
    const { cache } = harness();
    for (let index = 0; index <= PREFETCH_MAX; index += 1) cache.prefetch(`/api/runs/r${String(index)}`);
    expect(cache.take("/api/runs/r0")).toBeNull();
    expect(cache.take("/api/runs/r1")).not.toBeNull();
    expect(cache.take(`/api/runs/r${String(PREFETCH_MAX)}`)).not.toBeNull();
  });
});

describe("settled", () => {
  it("keeps a finished survey's record, whether it completed or failed, and never one still running", () => {
    expect(settled(RUN, { status: "complete", events: [] })).toBe(true);
    expect(settled(RUN, { status: "failed", events: [] })).toBe(true);
    expect(settled(RUN, { status: "running", events: [] })).toBe(false);
  });

  it("keeps a kit that is ready with its contents, and never one being built, failed, or ready without them", () => {
    const kit = "/api/kits/tok";
    expect(settled(kit, { status: "ready", kit: { concept: {} } })).toBe(true);
    expect(settled(kit, { status: "ready", kit: null })).toBe(false);
    expect(settled(kit, { status: "ready" })).toBe(false);
    expect(settled(kit, { status: "building" })).toBe(false);
    expect(settled(kit, { status: "failed" })).toBe(false);
  });

  it("keeps nothing else, nor an answer it cannot read", () => {
    expect(settled("/api/examples", { status: "complete" })).toBe(false);
    expect(settled(RUN, null)).toBe(false);
    expect(settled(RUN, "complete")).toBe(false);
    expect(settled(RUN, [])).toBe(false);
  });
});
