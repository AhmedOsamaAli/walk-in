import { api } from "../api/client";
import type { Design, RenderResult, Shot } from "../api/types";
import { safeUrl } from "../lib/format";

const designs = new Map<string, Promise<Design>>();
const renders = new Map<string, Promise<RenderResult>>();

/** A concept's design sheet, fetched once per run and concept; a failure can be retried by opening it again. */
export function loadDesign(runId: string, index: number): Promise<Design> {
  const key = `${runId}:${index}`;
  let pending = designs.get(key);
  if (!pending) {
    pending = api.design(runId, index);
    designs.set(key, pending);
    pending.catch(() => designs.delete(key));
  }
  return pending;
}

// While the free volunteer queue is busy the server answers "queued" and keeps the job's place, so asking again resumes it.
async function requestRender(runId: string, index: number, shot: string, attempt = 0): Promise<RenderResult> {
  const result = await api.render(runId, index, shot);
  return result.queued && attempt < 3 ? requestRender(runId, index, shot, attempt + 1) : result;
}

/** Renders take seconds to minutes: one request per shot, shared across reopenings of the sheet. */
export function loadRender(runId: string, index: number, shot: string): Promise<RenderResult> {
  const key = `${runId}:${index}:${shot}`;
  let pending = renders.get(key);
  if (!pending) {
    pending = requestRender(runId, index, shot);
    renders.set(key, pending);
    // Anything but an image can be tried again by reopening the sheet.
    pending.then(
      (result) => {
        if (!safeUrl(result.image)) renders.delete(key);
      },
      () => renders.delete(key),
    );
  }
  return pending;
}

function isShot(value: unknown): value is Shot {
  return (
    typeof value === "object" &&
    value !== null &&
    "kind" in value &&
    typeof value.kind === "string" &&
    "label" in value &&
    typeof value.label === "string"
  );
}

export function shotsOf(design: Design): Shot[] {
  return Array.isArray(design.shots) ? design.shots.filter(isShot) : [];
}
