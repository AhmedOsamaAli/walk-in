import { api } from "../api/client";
import type { Design } from "../api/types";

const designs = new Map<string, Promise<Design>>();

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