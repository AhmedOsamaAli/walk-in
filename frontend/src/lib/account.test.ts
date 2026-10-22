import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { dateText, initials, plainError, SURVEY_STATUS, surveyOutcome } from "./account";

describe("account helpers", () => {
  it("writes a date in the reader's time zone", () => {
    expect(dateText("2026-10-22T23:30:00Z", { locale: "en-US", timeZone: "UTC" })).toBe("Oct 22, 2026");
    expect(dateText("2026-10-22T23:30:00Z", { locale: "en-US", timeZone: "Africa/Cairo" })).toBe("Oct 23, 2026");
    expect(dateText("nope")).toBe("");
  });

  it("draws an account's initials", () => {
    expect(initials("Ada Lovelace", "ada@example.com")).toBe("AL");
    expect(initials("  ada  ", "ada@example.com")).toBe("A");
    expect(initials("Ahmed Osama Ali", "a@example.com")).toBe("AA");
    expect(initials("", "tester@example.com")).toBe("T");
    expect(initials("", "")).toBe("?");
  });

  it("says what went wrong in plain words", () => {
    expect(plainError(new ApiError("That Google sign-in has expired.", 400, null, true))).toBe("That Google sign-in has expired.");
    expect(plainError(new ApiError("Request failed (401).", 401))).toBe("You're signed out. Sign in and try again.");
    expect(plainError(new ApiError("Request failed (403).", 403))).toBe("The server refused this request. Reload the page and try again.");
    expect(plainError(new ApiError("Request failed (502).", 502))).toBe("Walk-in's server had a problem. Try again in a moment.");
    expect(plainError(new ApiError("Too many requests. Try again in a while.", 429))).toBe("Too many requests. Try again in a while.");
    expect(plainError(new TypeError("Failed to fetch"))).toBe("Walk-in can't be reached. Check your connection and try again.");
    expect(plainError(new Error("boom"), "Your places could not be loaded.")).toBe("Your places could not be loaded.");
  });

  it("says what a saved survey came to", () => {
    expect(surveyOutcome({ status: "complete", headline: "Golden Hour" })).toBe("Leads with Golden Hour");
    expect(surveyOutcome({ status: "complete", headline: null })).toBe("Finished without a clear lead");
    expect(surveyOutcome({ status: "running", headline: "Golden Hour" })).toBe("Still running");
    expect(surveyOutcome({ status: "failed", headline: "Bakery" })).toBe("Stopped early; leads with Bakery");
    expect(surveyOutcome({ status: "failed", headline: null })).toBe("Stopped before it finished");
    expect(SURVEY_STATUS).toEqual({ running: "Running", complete: "Complete", failed: "Stopped" });
  });
});
