import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { KitStatus, KitView } from "../api/commerce";
import { followKit, KIT_GONE, KIT_POLL_TRIES, type KitPoll } from "./kit";

function view(status: KitStatus): KitView {
  return {
    token: "tok",
    status,
    survey_id: "r1",
    index: 0,
    name: "Golden Hour",
    created_at: "2026-10-22T16:00:00Z",
    survey_url: "/s/r1?sheet=0",
    is_owner: true,
    kit: null,
    error: status === "failed" ? "The copy could not be written." : null,
    campaign_url: null,
    refundable_until: "2026-11-05T16:00:00Z",
  };
}

/** A poll that answers with the given copies or errors in turn, and records what it passed on. */
function fakePoll(answers: (KitView | Error)[], { stopAfter = Infinity } = {}) {
  const updates: KitStatus[] = [];
  const failures: [string, boolean][] = [];
  let loads = 0;
  let waits = 0;
  const poll: KitPoll = {
    load: () => {
      const answer = answers[loads];
      loads += 1;
      if (!answer) return Promise.reject(new Error("No more answers"));
      return answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer);
    },
    wait: () => {
      waits += 1;
      return Promise.resolve(waits <= stopAfter);
    },
    cancelled: () => waits > stopAfter,
    update: (next) => updates.push(next.status),
    fail: (message, gone) => failures.push([message, gone]),
  };
  return { poll, updates, failures, loads: () => loads };
}

describe("following a kit while it is built", () => {
  it("polls until the kit is ready, passing on every copy", async () => {
    const { poll, updates, failures, loads } = fakePoll([view("building"), view("building"), view("ready"), view("ready")]);
    await followKit(poll);
    expect(updates).toEqual(["building", "building", "ready"]);
    expect(failures).toEqual([]);
    expect(loads()).toBe(3);
  });

  it("stops at a failed or refunded kit", async () => {
    for (const status of ["failed", "refunded"] as const) {
      const { poll, updates } = fakePoll([view("building"), view(status)]);
      await followKit(poll);
      expect(updates).toEqual(["building", status]);
    }
  });

  it("rides out a few failed polls", async () => {
    const { poll, updates, failures } = fakePoll([new TypeError("Failed to fetch"), new ApiError("Request failed (502).", 502), view("ready")]);
    await followKit(poll);
    expect(updates).toEqual(["ready"]);
    expect(failures).toEqual([]);
  });

  it("gives up after failing polls in a row, in plain words", async () => {
    const errors = Array.from({ length: KIT_POLL_TRIES }, () => new ApiError("Request failed (502).", 502));
    const { poll, updates, failures, loads } = fakePoll([view("building"), ...errors, view("ready")]);
    await followKit(poll);
    expect(updates).toEqual(["building"]);
    expect(failures).toEqual([["Walk-in's server had a problem. Try again in a moment.", false]]);
    expect(loads()).toBe(1 + KIT_POLL_TRIES);
  });

  it("stops at once when the kit is gone", async () => {
    const { poll, failures, loads } = fakePoll([new ApiError("Not found", 404), view("ready")]);
    await followKit(poll);
    expect(failures).toEqual([[KIT_GONE, true]]);
    expect(loads()).toBe(1);
  });

  it("stops when the page lets go of the kit", async () => {
    const { poll, updates, loads } = fakePoll([view("building"), view("building"), view("ready")], { stopAfter: 1 });
    await followKit(poll);
    expect(updates).toEqual(["building"]);
    expect(loads()).toBe(1);
  });
});
