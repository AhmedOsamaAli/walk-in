import type { Design, GeocodeResult, HeatCell, Preset, RenderResult, RunRequest, Walk, WalkMinutes } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** The server's own `detail` message when it sent one, otherwise a sentence about the status. */
export async function errorText(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Not JSON: describe the status instead.
  }
  return response.status === 429 ? "Too many requests. Try again in a while." : `Request failed (${response.status}).`;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function query(params: Record<string, string | number>): string {
  return new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)])).toString();
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new ApiError(await errorText(response), response.status);
  return (await response.json()) as T;
}

function post(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

export const api = {
  presets: () => request<Preset[]>("/api/presets"),
  geocode: (text: string) => request<GeocodeResult[]>(`/api/geocode?${query({ q: text })}`),
  catchment: (lat: number, lon: number, minutes: WalkMinutes, signal?: AbortSignal) =>
    request<Walk>(`/api/catchment?${query({ lat, lon, minutes })}`, { signal }),
  heatmap: (lat: number, lon: number, tag: string) =>
    request<{ cells?: HeatCell[] }>(`/api/heatmap?${query({ lat, lon, tag })}`),
  design: (runId: string, index: number) => request<Design>("/api/design", post({ run_id: runId, index })),
  render: (runId: string, index: number, shot: string) =>
    request<RenderResult>("/api/render", post({ run_id: runId, index, shot })),
};

/** Opens a survey's event stream; read it with `readEvents`. */
export async function openRun(run: RunRequest, signal: AbortSignal): Promise<ReadableStream<Uint8Array<ArrayBuffer>>> {
  const params = query({
    lat: run.lat.toFixed(6),
    lon: run.lon.toFixed(6),
    label: run.label,
    focus: run.focus,
    notes: run.notes,
    minutes: run.minutes,
  });
  const response = await fetch(`/api/run?${params}`, { signal, headers: { Accept: "text/event-stream" } });
  if (!response.ok) throw new ApiError(await errorText(response), response.status);
  if (!response.body) throw new Error("The server sent no survey stream.");
  return response.body;
}
