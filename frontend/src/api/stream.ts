import type { SurveyEvent } from "./types";

/** One server-sent event with its JSON data parsed. */
export interface ServerEvent {
  event: string;
  data: unknown;
}

/** Parses one event block (the lines between blank lines); comments, ids and events without JSON data yield null. */
export function parseEvent(block: string): ServerEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value.trim() || "message";
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) as unknown };
  } catch {
    return null;
  }
}

/** A parser fed text as it arrives; it returns the events completed by each chunk and keeps the rest. */
export function createEventParser(): (text: string) => ServerEvent[] {
  let buffer = "";
  return (text) => {
    buffer += text;
    // A trailing CR may be the first half of a CRLF split across chunks, so it waits for the next chunk.
    const held = buffer.endsWith("\r") ? "\r" : "";
    const blocks = (held ? buffer.slice(0, -1) : buffer).replace(/\r\n?/g, "\n").split("\n\n");
    buffer = (blocks.pop() ?? "") + held;
    return blocks.map(parseEvent).filter((event) => event !== null);
  };
}

export async function* readEvents(stream: ReadableStream<Uint8Array<ArrayBuffer>>): AsyncGenerator<ServerEvent> {
  const reader = stream.pipeThrough(new TextDecoderStream()).getReader();
  const push = createEventParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      yield* push(value);
    }
  } finally {
    reader.releaseLock();
  }
}

const SURVEY_EVENTS: ReadonlySet<string> = new Set<SurveyEvent["event"]>([
  "run",
  "status",
  "catchment",
  "agent",
  "replay",
  "finding",
  "explored",
  "block",
  "demand",
  "gaps",
  "taste",
  "concepts",
  "baseline",
  "notice",
  "error",
  "done",
]);

/** The survey event a server event carries, or null for events this app does not know. */
export function toSurveyEvent({ event, data }: ServerEvent): SurveyEvent | null {
  if (!SURVEY_EVENTS.has(event) || typeof data !== "object" || data === null) return null;
  return { event, data } as SurveyEvent;
}
