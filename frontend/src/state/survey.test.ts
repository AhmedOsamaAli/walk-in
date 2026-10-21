import { describe, expect, it } from "vitest";
import type { GapRow, StepState, SurveyEvent } from "../api/types";
import { currentStep, initialSurvey, surveyProgress, surveyReducer, type SurveyState } from "./survey";

const started = surveyReducer(initialSurvey, { type: "start", startedAt: 1000 });

function play(state: SurveyState, ...events: [SurveyEvent, number][]): SurveyState {
  return events.reduce((next, [event, at]) => surveyReducer(next, { type: "event", event, at }), state);
}

function status(step: string, state: StepState, label = `Step ${step}`): SurveyEvent {
  return { event: "status", data: { step, state, label } };
}

function gap(genre: string, score: number, extra: Partial<GapRow> = {}): GapRow {
  return {
    genre_id: `urn:tag:genre:place:${genre.toLowerCase().replace(/ /g, "_")}`,
    genre,
    demand_rank: 2,
    ref_rank: 6,
    nearby_count: 2,
    nearby_capped: false,
    favorites_kind: "local",
    favorites_total: 5,
    favorites_far: 4,
    median_favorite_km: 2.4,
    expected_nearby: 3.5,
    lift: 0.4,
    relative_supply: 0.7,
    leakage: 0.71,
    evidence: "ok",
    gap_score: score,
    ...extra,
  };
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
});
