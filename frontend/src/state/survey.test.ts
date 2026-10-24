import { describe, expect, it } from "vitest";
import type { RunSite, SurveyEvent } from "../api/types";
import { gap, RAW, recordFrom, recordOf, RUN_EVENT, SITE, status, TIMELINE } from "./fixtures";
import { currentStep, initialSurvey, RECORD_ENDED, RECORD_FAILED, surveyProgress, surveyReducer, type SurveyState } from "./survey";

const started = surveyReducer(initialSurvey, { type: "start", startedAt: 1000 });

function play(state: SurveyState, ...events: [SurveyEvent, number][]): SurveyState {
  return events.reduce((next, [event, at]) => surveyReducer(next, { type: "event", event, at }), state);
}

const done: SurveyEvent = { event: "done", data: { run_id: "r1", seconds: 41.3, qloo_calls: 57, cache_hits: 3 } };

describe("surveyReducer", () => {
  it("starts each run from scratch and counts the runs", () => {
    const first = play(started, [{ event: "run", data: { run_id: "r1", llm: false } }, 0]);
    const second = surveyReducer(first, { type: "start", startedAt: 5000 });
    expect(second).toMatchObject({ run: 2, status: "running", streaming: true, startedAt: 5000, runId: null, log: [] });
  });

  it("logs the run and keeps it as the latest note", () => {
    const state = play(started, [{ event: "run", data: { run_id: "r1", llm: false } }, 0.05]);
    expect(state.runId).toBe("r1");
    expect(state.log).toEqual([
      { id: 0, at: 0.05, kind: "info", text: "Survey r1 started · evidence rules (no LLM key set)", status: "" },
    ]);
    expect(state.latest).toBe("Survey r1 started · evidence rules (no LLM key set)");
  });

  it("gives a step one log line that turns from running to a check mark with its time", () => {
    const state = play(
      started,
      [status("walk", "running", "Tracing a 10-minute walk"), 0.1],
      [{ event: "finding", data: { text: "A finding" } }, 0.4],
      [status("walk", "done", "Tracing a 10-minute walk"), 1.26],
    );
    expect(state.log.map(({ id, kind, text, status: mark }) => [id, kind, text, mark])).toEqual([
      [0, "done", "Tracing a 10-minute walk", "✓ 1.3s"],
      [1, "finding", "A finding", ""],
    ]);
  });

  it("logs a step that reports only its end", () => {
    const state = play(started, [status("block", "done"), 2]);
    expect(state.log).toHaveLength(1);
    expect(state.log[0]).toMatchObject({ kind: "done", status: "✓ 2.0s" });
  });

  it("moves the progress for the pipeline steps but not for the agent's thinking steps", () => {
    const pipeline = play(started, [status("walk", "running"), 0], [status("walk", "done"), 1]);
    expect(surveyProgress(pipeline)).toBeCloseTo(1 / 6);
    const thinking = play(
      pipeline,
      [status("agent-0", "running", "Agent reads the evidence"), 2],
      [status("agent-0", "done", "Agent reads the evidence"), 3],
      [status("agent-1", "running", "Agent weighs what it found"), 3],
    );
    expect(surveyProgress(thinking)).toBeCloseTo(1 / 6);
    expect(currentStep(thinking)?.label).toBe("Agent weighs what it found");
  });

  it("shows the latest running step as current while steps overlap", () => {
    const state = play(
      started,
      [status("block", "running", "Reading every place"), 1],
      [status("demand", "running", "Ranking what locals engage with"), 1],
      [status("demand", "done", "Ranking what locals engage with"), 2],
    );
    expect(currentStep(state)?.label).toBe("Reading every place");
  });

  it("ignores the retired crowd step", () => {
    const state = play(started, [status("crowd", "running"), 1], [status("crowd", "done"), 2]);
    expect(state.log).toEqual([]);
    expect(state.steps).toEqual([]);
  });

  it("opens the first gap when the gap table arrives, and toggles gaps", () => {
    const state = play(started, [{ event: "gaps", data: { rows: [gap("Seafood", 67), gap("Wine Bar", 41)] } }, 3]);
    expect(state.openGap).toBe(0);
    const second = surveyReducer(state, { type: "toggleGap", index: 1 });
    expect(second.openGap).toBe(1);
    expect(surveyReducer(second, { type: "toggleGap", index: 1 }).openGap).toBeNull();
  });

  it("opens no gap for an empty gap table", () => {
    const state = play(started, [{ event: "gaps", data: { rows: [] } }, 3]);
    expect(state.gaps).toEqual([]);
    expect(state.openGap).toBeNull();
  });

  it("appends a category the agent tested live and logs it as a finding", () => {
    const tested = gap("Bakery", 52, { source: "agent", nearby_count: 1, expected_nearby: 2.5 });
    const state = play(
      started,
      [{ event: "gaps", data: { rows: [gap("Seafood", 67)] } }, 3],
      [{ event: "agent", data: { tool: "test_category", args: { category: "bakery", reason: "Fans love pastry" } } }, 4],
      [{ event: "explored", data: { row: tested } }, 5],
    );
    expect(state.gaps?.map((row) => row.genre)).toEqual(["Seafood", "Bakery"]);
    expect(state.openGap).toBe(0);
    expect(state.log.map((line) => [line.kind, line.text])).toEqual([
      ["agent", "Agent tests a hunch live on Qloo: bakery — Fans love pastry"],
      ["finding", "Tested live: Bakery scores 52 · 1 inside the walk, ~2.5 typical"],
    ]);
    expect(state.latest).toBe("Tested live: Bakery scores 52 · 1 inside the walk, ~2.5 typical");
  });

  it("stores the evidence sections as they arrive", () => {
    const state = play(
      started,
      [{ event: "catchment", data: { minutes: 10, source: "street network", ring: [[1, 2]], area_km2: 1.2, radius_m: 600 } }, 1],
      [{ event: "block", data: { summary: { place_count: 12, top_genres: [["Cafe", 3]] }, places: [] } }, 2],
      [{ event: "demand", data: { cues: ["Jazz"] } }, 2],
      [{ event: "taste", data: { brands: [{ name: "Brand" }] } }, 3],
      [{ event: "concepts", data: { concepts: [], mode: "none", note: "Not enough data" } }, 4],
      [{ event: "baseline", data: { concepts: [{ name: "Coffee shop" }] } }, 4],
    );
    expect(state.catchment?.radius_m).toBe(600);
    expect(state.block?.summary.place_count).toBe(12);
    expect(state.cues).toEqual(["Jazz"]);
    expect(state.taste?.brands).toEqual([{ name: "Brand" }]);
    expect(state.concepts?.note).toBe("Not enough data");
    expect(state.baseline).toEqual([{ name: "Coffee shop" }]);
  });

  it("completes on done with the run's summary and full progress", () => {
    const state = play(started, [status("walk", "running"), 0], [status("walk", "done"), 1], [done, 41.5]);
    expect(state.status).toBe("complete");
    expect(state.summary).toEqual(done.data);
    expect(surveyProgress(state)).toBe(1);
    expect(state.log.at(-1)).toMatchObject({ kind: "done", text: "Survey complete", status: "✓" });
  });

  it("stops on a server error and closes the steps that will never finish", () => {
    const state = play(
      started,
      [status("gaps", "running", "Comparing supply"), 2],
      [{ event: "error", data: { message: "Qloo is unavailable." } }, 3],
      [done, 3.1],
    );
    expect(state.status).toBe("failed");
    expect(state.error).toBe("Qloo is unavailable.");
    expect(state.log.map((line) => [line.kind, line.text, line.status])).toEqual([
      ["failed", "Comparing supply", "✕"],
      ["err", "Qloo is unavailable.", ""],
      ["failed", "Survey stopped", "✕"],
    ]);
  });

  it("fails when the stream closes before the survey is done", () => {
    const state = surveyReducer(play(started, [status("walk", "running"), 0]), { type: "closed", at: 2 });
    expect(state).toMatchObject({ status: "failed", streaming: false });
    expect(state.log.map((line) => line.kind)).toEqual(["failed", "err"]);
  });

  it("reports a connection failure", () => {
    const state = surveyReducer(started, { type: "failed", message: "Too many requests. Try again in a while.", at: 0.2 });
    expect(state).toMatchObject({ status: "failed", streaming: false, error: "Too many requests. Try again in a while." });
  });

  it("stays complete when late events and the end of the stream arrive", () => {
    const complete = play(started, [done, 2]);
    const late = play(complete, [{ event: "baseline", data: { concepts: [{ name: "Wine bar" }] } }, 3]);
    const closed = surveyReducer(late, { type: "closed", at: 3.2 });
    expect(closed).toMatchObject({ status: "complete", streaming: false, baseline: [{ name: "Wine bar" }] });
  });

  it("resets to the brief and keeps counting runs", () => {
    const state = surveyReducer(play(started, [done, 1]), { type: "reset" });
    expect(state).toEqual({ ...initialSurvey, run: 1 });
  });

  it("keeps the verdict on the owner's idea and logs its stamp", () => {
    const opening = surveyReducer(initialSurvey, { type: "start", startedAt: 0, intent: "open" });
    const verdict = {
      query: "bakery",
      found: true,
      genre: "Bakery",
      level: "weak" as const,
      headline: "Bakery is a weak gap here (#9 of 9): locals rank it only #21 among place types.",
      position: 9,
      of: 9,
      evidence: ["2 bakeries inside the 10-minute walk."],
    };
    const state = play(opening, [{ event: "verdict", data: verdict }, 4]);
    expect(state.intent).toBe("open");
    expect(state.verdict).toEqual(verdict);
    expect(state.latest).toBe(`Verdict · Weak · ${verdict.headline}`);
  });

  it("keeps the owner's place and the moves when improving it", () => {
    const improving = surveyReducer(initialSurvey, { type: "start", startedAt: 0, intent: "improve" });
    const place = { id: "p1", name: "Suerte", genres: ["Mexican"], lat: 30.26, lon: -97.72 };
    const improve = {
      place,
      genre: "Mexican",
      moves: [{ title: "Own the high end", why: "Few of the Mexican places people here love are priced like Suerte: most are cheaper." }],
      experience: null,
      comparison: {
        peers: 10,
        peers_label: "places locals love",
        comparable: false,
        peer_names: ["Tamale House"],
        rating: { place: 4.6, peers: 4.3 },
        hours: { place: null, peers: null },
        offer: {},
        known_for: ["suadero tacos"],
        complaints: [],
        peers_known_for: ["margaritas"],
      },
    };
    const state = play(
      improving,
      [{ event: "place", data: { place, site: { lat: 30.26, lon: -97.72, label: "Suerte" } } }, 0.5],
      [{ event: "improve", data: improve }, 6],
    );
    expect(state.place?.name).toBe("Suerte");
    expect(state.improve).toEqual(improve);
    expect(state.log.map((line) => line.text)).toEqual(["Found Suerte on Qloo · Mexican", "1 move from the places locals love"]);
  });

  it("logs the server's note when a place cannot be compared", () => {
    const note = "Qloo has no category for this place, so there is nothing to compare.";
    const state = play(started, [{ event: "improve", data: { note } }, 3]);
    expect(state.improve).toEqual({ note });
    expect(state.latest).toBe(note);
  });

  it("measures progress on the intent's own pipeline", () => {
    const steps = (state: SurveyState, names: string[]) =>
      play(state, ...names.map((name, k): [SurveyEvent, number] => [status(name, "done"), k]));
    const improving = surveyReducer(initialSurvey, { type: "start", startedAt: 0, intent: "improve" });
    expect(surveyProgress(steps(improving, ["place", "walk", "block", "demand", "taste", "gaps"]))).toBeCloseTo(6 / 7);
    const opening = surveyReducer(initialSurvey, { type: "start", startedAt: 0, intent: "open" });
    expect(surveyProgress(steps(opening, ["walk", "block", "demand", "taste", "gaps", "verdict"]))).toBeCloseTo(6 / 7);
    expect(surveyProgress(steps(started, ["walk", "block", "demand", "taste", "gaps", "agent-0"]))).toBeCloseTo(5 / 6);
  });

  it("keeps the site and the intent the server read for the run", () => {
    const opening = play(started, [{ event: "run", data: { run_id: "r9", llm: false, site: { ...SITE, intent: "open" } } }, 0]);
    expect(opening.intent).toBe("open");
    expect(opening.site).toMatchObject({ lat: SITE.lat, lon: SITE.lon, label: SITE.label, business: "" });
    const odd = { lat: "30.2", lon: -97.7, label: "Pin", intent: "teleport" } as unknown as RunSite;
    const unplaced = play(started, [{ event: "run", data: { run_id: "r9", llm: false, site: odd } }, 0]);
    expect(unplaced).toMatchObject({ site: null, intent: "explore" });
  });
});

describe("a recorded survey", () => {
  const streamed = surveyReducer(play(started, ...TIMELINE), { type: "closed", at: 23.1 });
  const restore = (record: ReturnType<typeof recordOf>) =>
    surveyReducer(initialSurvey, { type: "restore", record, startedAt: 1000 });

  it("replays into the very state its stream left, at the recorded times", () => {
    const restored = restore(recordOf("complete"));
    expect({ ...restored, recorded: null }).toEqual(streamed);
    expect(restored).toMatchObject({ status: "complete", streaming: false, recorded: RAW.length, runId: "r1" });
    expect(restored.log.map((line) => line.at)).toEqual([0.01, 0.01, 0.02, 1.42, 5.1, 9, 12.5, 21.6]);
  });

  it("merges only the events a newer copy adds, however often the same copy comes back", () => {
    const early = restore(recordOf("running", 6));
    expect(early).toMatchObject({ status: "running", streaming: true, recorded: 6, block: { places: [] }, gaps: null });
    expect(surveyReducer(early, { type: "recorded", record: recordOf("running", 6) })).toBe(early);
    const later = surveyReducer(early, { type: "recorded", record: recordOf("running", 13) });
    expect(later.gaps?.map((row) => row.genre)).toEqual(["Seafood", "Wine Bar"]);
    expect(surveyReducer(later, { type: "recorded", record: recordOf("running", 13) })).toBe(later);
    const ended = surveyReducer(later, { type: "recorded", record: recordOf("complete") });
    expect(surveyReducer(ended, { type: "recorded", record: recordOf("complete") })).toBe(ended);
    expect({ ...ended, recorded: null }).toEqual(streamed);
  });

  it("stays complete while the late baseline is still to be recorded", () => {
    const done = restore(recordOf("running", RAW.length - 1));
    expect(done).toMatchObject({ status: "complete", streaming: true, baseline: [] });
    const late = surveyReducer(done, { type: "recorded", record: recordOf("complete") });
    expect(late).toMatchObject({ status: "complete", streaming: false, baseline: [{ name: "Coffee shop" }] });
  });

  it("shows a failed run and its error as the live view showed them", () => {
    const failing: [SurveyEvent, number][] = [
      [RUN_EVENT, 0.01],
      [status("walk", "running", "Tracing"), 0.02],
      [{ event: "error", data: { message: "Qloo is unavailable." } }, 2],
      [{ event: "done", data: { run_id: "r1", seconds: 2.1, qloo_calls: 3, cache_hits: 0 } }, 2.1],
    ];
    const live = surveyReducer(play(started, ...failing), { type: "closed", at: 2.2 });
    const restored = restore(recordFrom("failed", failing));
    expect({ ...restored, recorded: null }).toEqual(live);
    expect(restored).toMatchObject({ status: "failed", streaming: false, error: "Qloo is unavailable." });
  });

  it("fails a run that ended before it finished, closing the steps it left running", () => {
    const restored = restore(recordOf("failed", 5));
    expect(restored).toMatchObject({ status: "failed", streaming: false, error: RECORD_ENDED });
    expect(restored.steps.map((step) => [step.step, step.state])).toEqual([
      ["walk", "done"],
      ["block", "failed"],
    ]);
    expect(restored.log.at(-1)).toMatchObject({ kind: "err", text: RECORD_ENDED, at: 1.42 });
  });

  it("shows the failure of a run the server recorded as failed though its events finished", () => {
    const restored = restore(recordOf("failed"));
    expect(restored).toMatchObject({ status: "failed", streaming: false, error: RECORD_FAILED, concepts: streamed.concepts });
    expect(restored.log.at(-1)).toMatchObject({ kind: "err", text: RECORD_FAILED, at: 23 });
    const polled = surveyReducer(restore(recordOf("running", RAW.length - 1)), { type: "recorded", record: recordOf("failed") });
    expect({ ...polled, recorded: null }).toEqual({ ...restored, recorded: null });
  });

  it("ignores copies of another run, and copies while a run streams live", () => {
    const restored = restore(recordOf("running", 6));
    expect(surveyReducer(restored, { type: "recorded", record: { ...recordOf("complete"), id: "r2" } })).toBe(restored);
    const live = play(started, [RUN_EVENT, 0.01]);
    expect(surveyReducer(live, { type: "recorded", record: recordOf("complete") })).toBe(live);
  });

  it("starts each restore from scratch and counts it as a new run", () => {
    const first = restore(recordOf("complete"));
    const second = surveyReducer(first, { type: "restore", record: recordOf("running", 2), startedAt: 5000 });
    expect(second).toMatchObject({ run: 2, startedAt: 5000, recorded: 2, gaps: null, concepts: null, summary: null });
    expect(second.log).toHaveLength(3);
  });
});
