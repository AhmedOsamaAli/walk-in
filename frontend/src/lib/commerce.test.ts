import { describe, expect, it } from "vitest";
import {
  absoluteUrl,
  campaignStatusText,
  dateInput,
  dateTimeText,
  deadlineFrom,
  deadlineProblem,
  deadlineRange,
  defaultDeadline,
  inSandbox,
  moneyText,
  normalizeAmount,
  timeLeft,
  trackedUrl,
  websiteUrl,
} from "./commerce";

const NOW = Date.parse("2026-10-22T16:00:00Z");
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const at = (ms: number) => new Date(NOW + ms).toISOString();

describe("money", () => {
  it("writes amounts the way a price tag does", () => {
    expect(moneyText("19.00", "USD")).toBe("$19");
    expect(moneyText("25.50", "USD")).toBe("$25.50");
    expect(moneyText("1200.00", "USD")).toBe("$1,200");
    expect(moneyText("19.00", "EUR")).toBe("€19");
    expect(moneyText("19.00", "XYZ1")).toBe("19.00 XYZ1");
    expect(moneyText("", "USD")).toBe("USD");
  });

  it("reads what the owner types as an amount", () => {
    expect(normalizeAmount("25")).toBe("25.00");
    expect(normalizeAmount(" $25.5 ")).toBe("25.50");
    expect(normalizeAmount("12,75")).toBe("12.75");
    for (const text of ["", "0", "-5", "abc", "25.505", "1e3", "25 dollars"]) expect(normalizeAmount(text)).toBeNull();
  });

  it("treats every payment as a test unless PayPal is live", () => {
    expect(inSandbox(null)).toBe(true);
    expect(inSandbox({ enabled: true, client_id: "A", environment: "sandbox", currency: "USD", kit_price: "19.00" })).toBe(true);
    expect(inSandbox({ enabled: true, client_id: "A", environment: "production", currency: "USD", kit_price: "19.00" })).toBe(false);
  });
});

describe("time", () => {
  it("counts down to a deadline in the largest unit that reads well", () => {
    expect(timeLeft(at(26 * DAY + 5 * HOUR), NOW)).toEqual({ closed: false, text: "26 days left" });
    expect(timeLeft(at(2 * DAY), NOW)).toEqual({ closed: false, text: "2 days left" });
    expect(timeLeft(at(DAY + 4 * HOUR + 10 * MINUTE), NOW)).toEqual({ closed: false, text: "1 day, 4 hours left" });
    expect(timeLeft(at(DAY + 1 * HOUR), NOW)).toEqual({ closed: false, text: "1 day, 1 hour left" });
    expect(timeLeft(at(DAY + 30 * MINUTE), NOW)).toEqual({ closed: false, text: "1 day left" });
    expect(timeLeft(at(5 * HOUR + 59 * MINUTE), NOW)).toEqual({ closed: false, text: "5 hours left" });
    expect(timeLeft(at(HOUR + 12 * MINUTE), NOW)).toEqual({ closed: false, text: "1 hour, 12 minutes left" });
    expect(timeLeft(at(HOUR), NOW)).toEqual({ closed: false, text: "1 hour left" });
    expect(timeLeft(at(MINUTE), NOW)).toEqual({ closed: false, text: "1 minute left" });
    expect(timeLeft(at(20_000), NOW)).toEqual({ closed: false, text: "Under a minute left" });
    expect(timeLeft(at(0), NOW)).toEqual({ closed: true, text: "Closed" });
    expect(timeLeft(at(-DAY), NOW)).toEqual({ closed: true, text: "Closed" });
    expect(timeLeft("not a date", NOW)).toEqual({ closed: true, text: "Closed" });
  });

  it("writes deadlines in the reader's time zone", () => {
    const zoned = { locale: "en-US", timeZone: "UTC" };
    expect(dateTimeText("2026-11-05T18:00:00Z", zoned)).toBe("Thu, Nov 5, 6:00 PM UTC");
    expect(dateTimeText("nope")).toBe("");
  });

  it("turns the deadline form's local date and time into an instant", () => {
    expect(deadlineFrom("2026-11-05", "20:00")).toBe(new Date(2026, 10, 5, 20, 0).toISOString());
    expect(deadlineFrom("2026-02-30", "20:00")).toBeNull();
    expect(deadlineFrom("2026-11-05", "")).toBeNull();
    expect(deadlineFrom("", "20:00")).toBeNull();
    expect(deadlineFrom("05/11/2026", "20:00")).toBeNull();
  });

  it("offers deadlines from today to 27 days out, and starts three weeks out at 8 pm", () => {
    expect(deadlineRange(NOW)).toEqual({ min: dateInput(NOW), max: dateInput(NOW + 27 * DAY) });
    const first = defaultDeadline(NOW);
    expect(first).toEqual({ date: dateInput(NOW + 21 * DAY), time: "20:00" });
    expect(deadlineProblem(deadlineFrom(first.date, first.time), NOW)).toBeNull();
    expect(dateInput(new Date(2026, 0, 9, 12).getTime())).toBe("2026-01-09");
  });

  it("explains a deadline that cannot work", () => {
    expect(deadlineProblem(null, NOW)).toBe("Pick a date and a time for the deadline.");
    expect(deadlineProblem(at(-MINUTE), NOW)).toBe("Pick a deadline in the future.");
    expect(deadlineProblem(at(27 * DAY), NOW)).toBeNull();
    expect(deadlineProblem(at(27 * DAY + MINUTE), NOW)).toMatch(/^Pick a deadline at most 27 days from now/);
  });
});

describe("links and names", () => {
  it("reads the owner's website, adding the scheme they left out", () => {
    expect(websiteUrl("goldenhour.cafe")).toBe("https://goldenhour.cafe/");
    expect(websiteUrl(" https://goldenhour.cafe/menu?x=1 ")).toBe("https://goldenhour.cafe/menu?x=1");
    expect(websiteUrl("http://localhost:8000")).toBe("http://localhost:8000/");
    for (const text of ["", "golden hour", "javascript:alert(1)", "ftp://goldenhour.cafe", "goldenhour"]) {
      expect(websiteUrl(text)).toBeNull();
    }
  });

  it("adds a channel's tags to the landing page", () => {
    const query = "utm_source=poster&utm_medium=qr&utm_campaign=golden-hour-launch";
    expect(trackedUrl("https://goldenhour.cafe/", query)).toBe(`https://goldenhour.cafe/?${query}`);
    expect(trackedUrl("https://goldenhour.cafe/menu?lang=en#top", query)).toBe(`https://goldenhour.cafe/menu?lang=en&${query}#top`);
    expect(trackedUrl("https://goldenhour.cafe/?utm_source=old", query)).toBe(`https://goldenhour.cafe/?utm_source=poster&utm_medium=qr&utm_campaign=golden-hour-launch`);
    expect(absoluteUrl("/p/c1?withdraw=w", "https://walk-in.example")).toBe("https://walk-in.example/p/c1?withdraw=w");
  });

  it("names a campaign's state", () => {
    expect(campaignStatusText("open")).toBe("Open");
    expect(campaignStatusText("open", false)).toBe("Closed, settling");
    expect(campaignStatusText("collected")).toBe("Funded");
    expect(campaignStatusText("partial")).toBe("Funded, still collecting");
    expect(campaignStatusText("expired")).toBe("Ended short of its goal");
    expect(campaignStatusText("cancelled")).toBe("Cancelled");
  });
});
