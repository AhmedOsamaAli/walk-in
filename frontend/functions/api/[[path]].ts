/**
 * Walk-in's front door. Cloudflare Pages serves the web app, which never sleeps, and this function hands every /api
 * request to the backend on Render, so the app, its sign-in cookie and the survey stream share one origin.
 *
 * Render's free instance sleeps after 15 idle minutes and takes about a minute to wake. Until it answers, API calls get
 * 503 {"waking": true} from here instead of Render's own page, and the app shows its own note while it retries; the
 * answers the backend marks shareable (examples, kits, presets, config) are kept at the edge meanwhile, and still open.
 * How: ../_lib/proxy.ts; what is kept, and for how long: ../_lib/cache.ts.
 */
import type { EdgeCache } from "../_lib/cache";
import { frontDoor, wait, type Env } from "../_lib/proxy";

interface Context {
  request: Request;
  env: Env;
  /** Keeps the function running after the answer has gone, for work such as the cache writes. */
  waitUntil: (work: Promise<unknown>) => void;
}

/** Cloudflare's own cache, `caches.default`; null in a runtime without one, where nothing is kept. */
function edgeCache(): EdgeCache | null {
  return (globalThis as { caches?: { default?: EdgeCache } }).caches?.default ?? null;
}

export function onRequest(context: Context): Promise<Response> {
  return frontDoor(context.request, {
    env: context.env,
    cache: edgeCache(),
    waitUntil: (work) => {
      context.waitUntil(work);
    },
    fetch: (request, init) => fetch(request, init),
    sleep: wait,
  });
}