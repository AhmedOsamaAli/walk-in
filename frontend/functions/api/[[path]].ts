/**
 * Walk-in's front door. Cloudflare Pages serves the web app, which never sleeps, and this function hands every /api
 * request to the backend on Render, so the app, its sign-in cookie and the survey stream share one origin.
 *
 * Render's free instance sleeps after 15 idle minutes and takes about a minute to wake. Until it answers, API calls get
 * 503 {"waking": true} from here instead of Render's own page, and the app shows its own note while it retries.
 */

interface Env {
  /** The backend's origin, such as https://walk-in-aoa2.onrender.com. */
  BACKEND_ORIGIN: string;
  /** Shared with the backend, which trusts X-Client-IP (the visitor's address, for rate limits) only with it. */
  PROXY_SECRET: string;
}

interface Context {
  request: Request;
  env: Env;
}

// Set here only: a visitor's own values for these are dropped.
const PROXY_HEADERS = ["x-client-ip", "x-proxy-secret", "x-forwarded-host"];

export async function onRequest({ request, env }: Context): Promise<Response> {
  const front = new URL(request.url);
  const backend = new URL(env.BACKEND_ORIGIN);
  const upstream = new Request(new URL(front.pathname + front.search, backend), request);
  for (const name of PROXY_HEADERS) upstream.headers.delete(name);
  upstream.headers.set("x-client-ip", request.headers.get("cf-connecting-ip") ?? "");
  upstream.headers.set("x-proxy-secret", env.PROXY_SECRET);
  upstream.headers.set("x-forwarded-host", front.host);

  let response: Response;
  try {
    response = await fetch(upstream, { redirect: "manual" });
  } catch {
    return waking();
  }
  const type = response.headers.get("content-type") ?? "";
  // While a free instance spins up, Render answers with a page of its own or a gateway error, never the API's JSON.
  if (type.startsWith("text/html") || (response.status >= 502 && response.status <= 504 && !type.includes("json"))) {
    return waking();
  }
  const location = response.headers.get("location");
  if (location?.startsWith(backend.origin)) {
    const headers = new Headers(response.headers);
    headers.set("location", front.origin + location.slice(backend.origin.length));
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  }
  return response;
}

function waking(): Response {
  return Response.json(
    { detail: "The survey engine is waking up; after a quiet spell that takes up to a minute.", waking: true },
    { status: 503, headers: { "retry-after": "3", "cache-control": "no-store" } },
  );
}
