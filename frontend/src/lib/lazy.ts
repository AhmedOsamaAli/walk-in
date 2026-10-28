/* The parts of the app that load when first needed, in chunks of their own (chunks.ts), so the first screen loads only
   what it shows; and the idle moments the app uses to load the next part before it is asked for. */
import { createElement, lazy, useState, type ComponentType } from "react";

/** A module loaded on first use, once: a later call joins the load under way, and one after a failure tries again. */
export interface LazyModule<M> {
  load: () => Promise<M>;
  /** Starts loading it ahead of need; a failure is left to the part that renders it. */
  preload: () => void;
  /** The module, once it has loaded; null until then. */
  current: () => M | null;
}

export function lazyModule<M>(importer: () => Promise<M>): LazyModule<M> {
  let loading: Promise<M> | null = null;
  let loaded: M | null = null;
  const load = () => {
    loading ??= importer().then(
      (module) => {
        loaded = module;
        return module;
      },
      (error: unknown) => {
        loading = null;
        throw error;
      },
    );
    return loading;
  };
  return {
    load,
    preload: () => {
      load().catch(() => undefined);
    },
    current: () => loaded,
  };
}

/** When the page last reloaded itself for a chunk it could not load, in this tab. */
const RELOADED_AT = "walk-in-reloaded-for-chunk";
const RELOAD_GAP_MS = 60_000;

/**
 * A chunk that will not load is most often one a newer deploy replaced while this page was open: the page reloads, onto
 * the new build, rather than show a part that cannot work. Never twice within a minute, so a chunk that truly will not
 * load ends in the part's error message instead of a loop. Whether it reloads.
 */
export function reloadForChunk(storage: Pick<Storage, "getItem" | "setItem">, now: number, reload: () => void): boolean {
  try {
    if (now - Number(storage.getItem(RELOADED_AT) ?? 0) < RELOAD_GAP_MS) return false;
    storage.setItem(RELOADED_AT, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

/**
 * A component of a lazy module, to render under <Suspense>: its module starts loading when it first renders, if not
 * before, and the boundary's fallback shows meanwhile. Rendered once its module is in, it shows at once, without the
 * fallback's frame that React.lazy would show first.
 */
export function lazyComponent<M, P extends object>(module: LazyModule<M>, pick: (loaded: M) => ComponentType<P>): ComponentType<P> {
  const Lazy = lazy(() =>
    module.load().then(
      (loaded) => ({ default: pick(loaded) }),
      (error: unknown) => {
        const reloading = reloadForChunk(window.sessionStorage, Date.now(), () => {
          window.location.reload();
        });
        if (reloading) return new Promise<never>(() => undefined);
        throw error;
      },
    ),
  );
  function LazyPart(props: P) {
    // Fixed for the part's life, so it never swaps one way of rendering for the other, which would remount it.
    const [loaded] = useState(module.current);
    return loaded ? createElement(pick(loaded), props) : createElement(Lazy as ComponentType<P>, props);
  }
  return LazyPart;
}

/** Runs `work` once the browser is idle, or after `timeout` ms at the latest; the function it returns cancels that. */
export function whenIdle(work: () => void, timeout = 3000): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(work, { timeout });
    return () => {
      window.cancelIdleCallback(handle);
    };
  }
  const timer = window.setTimeout(work, 500);
  return () => {
    window.clearTimeout(timer);
  };
}
