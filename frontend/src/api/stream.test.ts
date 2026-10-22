import { describe, expect, it } from "vitest";
import { createEventParser, parseEvent, readEvents, toRunRecord, toSurveyEvent, type ServerEvent } from "./stream";

function streamOf(chunks: Uint8Array<ArrayBuffer>[]): ReadableStream<Uint8Array<ArrayBuffer>> {
  return new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array<ArrayBuffer>>): Promise<ServerEvent[]> {
  const events: ServerEvent[] = [];
  for await (const event of readEvents(stream)) events.push(event);
  return events;
}

describe("parseEvent", () => {
  it("reads the event name and its JSON data", () => {
    expect(parseEvent('event: status\ndata: {"step":"walk"}')).toEqual({ event: "status", data: { step: "walk" } });
  });

  it("names events without an event field 'message'", () => {
    expect(parseEvent('data: {"ok":true}')).toEqual({ event: "message", data: { ok: true } });
  });

  it("joins data spread over several lines", () => {
    expect(parseEvent('event: block\ndata: {"place_count":\ndata: 95}')).toEqual({ event: "block", data: { place_count: 95 } });
  });

  it("accepts fields without the optional space and ignores ids and retries", () => {
    expect(parseEvent('id: 7\nretry: 1000\nevent:done\ndata:{"seconds":1.5}')).toEqual({ event: "done", data: { seconds: 1.5 } });
  });

  it("yields nothing for comments, events without data and data that is not JSON", () => {
    expect(parseEvent(": keep-alive")).toBeNull();
    expect(parseEvent("event: ping")).toBeNull();
    expect(parseEvent("event: run\ndata: {broken")).toBeNull();
  });
});

describe("createEventParser", () => {
  it("returns each event when its blank line arrives, across chunk boundaries", () => {
    const push = createEventParser();
    expect(push('event: run\ndata: {"run_')).toEqual([]);
    expect(push('id":"a1"}\n')).toEqual([]);
    expect(push('\nevent: done\ndata: {"seconds":2}\n\nevent: sta')).toEqual([
      { event: "run", data: { run_id: "a1" } },
      { event: "done", data: { seconds: 2 } },
    ]);
    expect(push('tus\ndata: {"step":"walk"}\n\n')).toEqual([{ event: "status", data: { step: "walk" } }]);
  });

  it("skips keep-alive comments between events", () => {
    const push = createEventParser();
    expect(push(': keep-alive\n\nevent: run\ndata: {"llm":false}\n\n: keep-alive\n\n')).toEqual([
      { event: "run", data: { llm: false } },
    ]);
  });

  it("does not mistake a CRLF split between chunks for a blank line", () => {
    const push = createEventParser();
    expect(push("event: status\r")).toEqual([]);
    expect(push('\ndata: {"step":"walk"}\r\n\r\n')).toEqual([{ event: "status", data: { step: "walk" } }]);
  });

  it("treats a lone CR as a line ending", () => {
    const push = createEventParser();
    expect(push('event: finding\rdata: {"text":"x"}\r\r')).toEqual([]);
    expect(push("event: next")).toEqual([{ event: "finding", data: { text: "x" } }]);
  });
});

describe("readEvents", () => {
  it("decodes a byte stream, including a character split between chunks", async () => {
    const bytes = new TextEncoder().encode('event: finding\ndata: {"text":"Café ✓"}\n\nevent: done\ndata: {}\n\n');
    const cut = bytes.indexOf(0xc3) + 1;
    const events = await collect(streamOf([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events).toEqual([
      { event: "finding", data: { text: "Café ✓" } },
      { event: "done", data: {} },
    ]);
  });

  it("drops an event the stream ended before finishing", async () => {
    const bytes = new TextEncoder().encode('event: run\ndata: {"llm":true}\n\nevent: done\ndata: {"sec');
    expect(await collect(streamOf([bytes]))).toEqual([{ event: "run", data: { llm: true } }]);
  });
});

describe("toSurveyEvent", () => {
  it("keeps the survey's events", () => {
    const event = toSurveyEvent({ event: "notice", data: { message: "Busy" } });
    expect(event).toEqual({ event: "notice", data: { message: "Busy" } });
  });

  it("drops events it does not know and data that is not an object", () => {
    expect(toSurveyEvent({ event: "crowd", data: {} })).toBeNull();
    expect(toSurveyEvent({ event: "status", data: "walk" })).toBeNull();
    expect(toSurveyEvent({ event: "done", data: null })).toBeNull();
  });
});

describe("toRunRecord", () => {
  it("reads a recorded run and its timed events", () => {
    const record = toRunRecord({
      id: "3f9a0c1b2d4e",
      status: "running",
      created_at: "2026-10-22T14:06:56+00:00",
      events: [
        ["run", { run_id: "3f9a0c1b2d4e", llm: true }, 0.01],
        ["status", { step: "walk", state: "running", label: "Tracing" }, 0.2],
      ],
    });
    expect(record).toEqual({
      id: "3f9a0c1b2d4e",
      status: "running",
      created_at: "2026-10-22T14:06:56+00:00",
      events: [
        ["run", { run_id: "3f9a0c1b2d4e", llm: true }, 0.01],
        ["status", { step: "walk", state: "running", label: "Tracing" }, 0.2],
      ],
    });
  });

  it("drops malformed events and keeps the rest in order", () => {
    const record = toRunRecord({
      id: "r1",
      status: "complete",
      events: [["run", {}, 0], "status", ["status", {}], [7, {}, 1], ["finding", { text: "x" }, "2"], ["done", {}, 3]],
    });
    expect(record?.events).toEqual([
      ["run", {}, 0],
      ["done", {}, 3],
    ]);
    expect(record?.created_at).toBe("");
  });

  it("is null for anything that is not a recorded run", () => {
    expect(toRunRecord(null)).toBeNull();
    expect(toRunRecord("r1")).toBeNull();
    expect(toRunRecord({ id: "r1", status: "paused", events: [] })).toBeNull();
    expect(toRunRecord({ id: 1, status: "running", events: [] })).toBeNull();
    expect(toRunRecord({ id: "r1", status: "running", events: {} })).toBeNull();
  });
});
