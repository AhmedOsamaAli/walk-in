import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { RunRecord, SurveyEvent } from "../api/types";
import { RAW, recordOf, TIMELINE } from "./fixtures";
import { followRecord, POLL_MS, POLL_TRIES, recordElapsed, RUN_GONE, RUN_STALLED, STALL_MS, type Poll } from "./record";
import { initialSurvey, surveyReducer, type SurveyAction, type SurveyState } from "./survey";

/** A poll over canned copies of the record, the last one repeating; each wait moves a fake clock on by one interval. */
function fakePoll(copies: (RunRecord | Error)[], waits = Infinity) {
  const actions: SurveyAction[] = [];
  let clock = 0;
  let loads = 0;
  let waited = 0;
  const poll: Poll = {
    load: () => {
      const copy = copies[Math.min(loads, copies.length - 1)] ?? new Error("No copy");
      loads += 1;
      return copy instanceof Error ? Promise.reject(copy) : Promise.resolve(copy);
    },
    wait: () => {
      waited += 1;
      clock += POLL_MS;
      return Promise.resolve(waited <= waits);
    },
    dispatch: (action) => {
      actions.push(action);
    },
    now: () => clock,
    at: () => clock / 1000,
    cancelled: () => waited > waits,
  };
  return { poll, actions, loads: () => loads };
}

function streamed(timeline: [SurveyEvent, number][]): SurveyState {
  const live = timeline.reduce(
    (state, [event, at]) => surveyReducer(state, { type: "event", event, at }),
    surveyReducer(initialSurvey, { type: "start", startedAt: 1000 }),
  );
  return surveyReducer(live, { type: "closed", at: 23.1 });
}

describe("followRecord", () => {
  it("polls a running survey until it ends, passing on only the copies with new events", async () => {
    const first = recordOf("running", 5);
    const { poll, actions, loads } = fakePoll([
      recordOf("running", 5),
      recordOf("running", 9),
      recordOf("running", 9),
      recordOf("running", 14),
      recordOf("complete"),
    ]);
    await followRecord(first, poll);
    expect(loads()).toBe(5);
    expect(actions.map((action) => (action.type === "recorded" ? action.record.events.length : action.type))).toEqual([
      9,
      14,
      RAW.length,
    ]);
    const restored = surveyReducer(initialSurvey, { type: "restore", record: first, startedAt: 1000 });
    const followed = actions.reduce(surveyReducer, restored);
    expect({ ...followed, recorded: null }).toEqual(streamed(TIMELINE));
  });

  it("reports a survey that disappears from the server", async () => {
    const { poll, actions, loads } = fakePoll([recordOf("running", 9), new ApiError("Not found", 404)]);
    await followRecord(recordOf("running", 5), poll);
    expect(loads()).toBe(2);
    expect(actions.map((action) => action.type)).toEqual(["recorded", "failed"]);
    expect(actions[1]).toEqual({ type: "failed", message: RUN_GONE, at: (2 * POLL_MS) / 1000 });
  });

  it("rides out a failed poll, and gives up after several in a row", async () => {
    const flaky = fakePoll([new Error("Network down"), recordOf("complete")]);
    await followRecord(recordOf("running", 5), flaky.poll);
    expect(flaky.actions.map((action) => action.type)).toEqual(["recorded"]);

    const down = fakePoll([new Error("Network down")]);
    await followRecord(recordOf("running", 5), down.poll);
    expect(down.loads()).toBe(POLL_TRIES);
    expect(down.actions).toEqual([{ type: "failed", message: "Network down", at: (POLL_TRIES * POLL_MS) / 1000 }]);
  });

  it("gives up on a survey that stops recording events", async () => {
    const { poll, actions, loads } = fakePoll([recordOf("running", 5)]);
    await followRecord(recordOf("running", 5), poll);
    expect(loads()).toBe(STALL_MS / POLL_MS);
    expect(actions).toEqual([{ type: "failed", message: RUN_STALLED, at: STALL_MS / 1000 }]);
  });

  it("stops without a word once cancelled", async () => {
    const before = fakePoll([recordOf("complete")], 0);
    await followRecord(recordOf("running", 5), before.poll);
    expect(before.loads()).toBe(0);
    expect(before.actions).toEqual([]);

    const actions: SurveyAction[] = [];
    let cancelled = false;
    await followRecord(recordOf("running", 5), {
      load: () => {
        cancelled = true;
        return Promise.resolve(recordOf("complete"));
      },
      wait: () => Promise.resolve(!cancelled),
      dispatch: (action) => {
        actions.push(action);
      },
      now: () => 0,
      at: () => 0,
      cancelled: () => cancelled,
    });
    expect(actions).toEqual([]);
  });
});

describe("recordElapsed", () => {
  const created = Date.parse("2026-10-22T14:00:00Z");
  const running = recordOf("running", 5);
  const last = 1.42;

  it("counts a running survey's time from when it started", () => {
    expect(recordElapsed(running, created + 30_000)).toBe(30);
    expect(recordElapsed({ ...running, created_at: "2026-10-22T17:00:00+03:00" }, created + 30_000)).toBe(30);
    expect(recordElapsed({ ...running, created_at: "2026-10-22T14:00:00" }, created + 30_000)).toBe(30);
  });

  it("falls back to its last event's time when the clocks cannot be trusted", () => {
    expect(recordElapsed(running, created - 5_000)).toBe(last);
    expect(recordElapsed(running, created + STALL_MS + 60_000)).toBe(last);
    expect(recordElapsed({ ...running, created_at: "" }, created + 30_000)).toBe(last);
    expect(recordElapsed({ ...running, events: [] }, created - 5_000)).toBe(0);
  });

  it("gives a finished survey's length by its last event", () => {
    expect(recordElapsed(recordOf("complete"), created + 30 * 60_000)).toBe(23);
  });
});
