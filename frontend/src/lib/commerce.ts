/* Payments only (launch kit and pledges): money, deadlines, tracked links and statuses. */
import type { CampaignStatus, KitStatus, PayPalConfig } from "../api/commerce";

export { dateText, plainError } from "./account";

/** Shown wherever money appears while PayPal runs in its sandbox. */
export const SANDBOX_NOTICE = "Test mode: PayPal sandbox, no real money";
export const JUDGES_NOTE = "Judges: test buyer details are in the README";
/** PayPal holds a pledge for 29 days; the last two are kept for collecting it. */
export const LONGEST_CAMPAIGN_DAYS = 27;
const DAY_MS = 86_400_000;

/** Every payment is a test one unless the server says PayPal is live. */
export function inSandbox(paypal: PayPalConfig | null | undefined): boolean {
  return paypal?.environment !== "production";
}

/** "$19", "$25.50", "€19": cents only when there are some. */
export function moneyText(amount: string, currency: string): string {
  const value = Number(amount);
  if (!amount.trim() || !Number.isFinite(value)) return `${amount} ${currency}`.trim();
  const whole = Number.isInteger(value);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** "25" or "$25.5" as the API writes amounts, "25.50"; null when it is not a positive amount with at most two decimals. */
export function normalizeAmount(text: string): string | null {
  const plain = text.trim().replace(/^[$€£]\s*/, "").replace(",", ".");
  if (!/^\d{1,6}(\.\d{1,2})?$/.test(plain)) return null;
  const value = Number(plain);
  return value > 0 ? value.toFixed(2) : null;
}

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

/** "26 days left", "1 day, 4 hours left", "12 minutes left"; closed once the deadline has passed. */
export function timeLeft(deadline: string, now: number): { closed: boolean; text: string } {
  const ms = Date.parse(deadline) - now;
  if (!Number.isFinite(ms) || ms <= 0) return { closed: true, text: "Closed" };
  const minutes = Math.floor(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  let text: string;
  if (days >= 2) text = plural(days, "day");
  else if (days === 1) text = hours > 24 ? `1 day, ${plural(hours - 24, "hour")}` : "1 day";
  else if (hours >= 2) text = plural(hours, "hour");
  else if (hours === 1) text = minutes > 60 ? `1 hour, ${plural(minutes - 60, "minute")}` : "1 hour";
  else if (minutes >= 1) text = plural(minutes, "minute");
  else return { closed: false, text: "Under a minute left" };
  return { closed: false, text: `${text} left` };
}

interface Zoned {
  locale?: string;
  timeZone?: string;
}

/** "Thu, Nov 5, 8:00 PM GMT+2": a deadline in the reader's own time zone, named. */
export function dateTimeText(iso: string, { locale, timeZone }: Zoned = {}): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleString(locale, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone,
  });
}

/** The browser's time zone, as the deadline form names it ("Africa/Cairo"). */
export function localZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

const pad = (value: number) => String(value).padStart(2, "0");

/** A moment as a date input's value, in local time: "2026-11-05". */
export function dateInput(ms: number): string {
  const day = new Date(ms);
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** A local date and time from the deadline form, as an ISO instant in UTC; null when either is missing or not real. */
export function deadlineFrom(date: string, time: string): string | null {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const clock = /^(\d{2}):(\d{2})$/.exec(time);
  if (!day || !clock) return null;
  const [year, month, dayOfMonth] = [Number(day[1]), Number(day[2]), Number(day[3])];
  const local = new Date(year, month - 1, dayOfMonth, Number(clock[1]), Number(clock[2]));
  const real = local.getFullYear() === year && local.getMonth() === month - 1 && local.getDate() === dayOfMonth;
  return real && !Number.isNaN(local.getTime()) ? local.toISOString() : null;
}

/** The form's first deadline: three weeks out, at 8 pm local time. */
export function defaultDeadline(now: number): { date: string; time: string } {
  return { date: dateInput(now + 21 * DAY_MS), time: "20:00" };
}

/** The dates the deadline's date input offers: today to 27 days from now. */
export function deadlineRange(now: number): { min: string; max: string } {
  return { min: dateInput(now), max: dateInput(now + LONGEST_CAMPAIGN_DAYS * DAY_MS) };
}

/** Why a deadline cannot be used, or null. The server checks the rest of the terms. */
export function deadlineProblem(iso: string | null, now: number): string | null {
  if (iso === null) return "Pick a date and a time for the deadline.";
  const at = Date.parse(iso);
  if (at <= now) return "Pick a deadline in the future.";
  if (at - now > LONGEST_CAMPAIGN_DAYS * DAY_MS) {
    return `Pick a deadline at most ${LONGEST_CAMPAIGN_DAYS} days from now: PayPal holds a pledge for 29 days, and the last two are kept for collecting it.`;
  }
  return null;
}

/** What the owner typed as their website, as a link: "walkin.cafe" -> "https://walkin.cafe/"; null if it is not one. */
export function websiteUrl(text: string): string | null {
  const typed = text.trim();
  if (!typed || /\s/.test(typed)) return null;
  try {
    const url = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(typed) ? typed : `https://${typed}`);
    const host = url.hostname;
    if ((url.protocol !== "https:" && url.protocol !== "http:") || !(host.includes(".") || host === "localhost")) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** The landing page with a channel's UTM tags; tags already on the page give way to the channel's. */
export function trackedUrl(base: string, query: string): string {
  const url = new URL(base);
  for (const [key, value] of new URLSearchParams(query)) url.searchParams.set(key, value);
  return url.href;
}

/** A path the API returns ("/p/abc") as a link to share. */
export function absoluteUrl(path: string, origin = window.location.origin): string {
  return new URL(path, origin).href;
}

export const KIT_STATUS: Record<KitStatus, string> = {
  building: "Building",
  ready: "Ready",
  failed: "Failed",
  refunded: "Refunded",
};

/** A campaign's state in a few words; an open one past its close is waiting to be settled. */
export function campaignStatusText(status: CampaignStatus, accepting = true): string {
  switch (status) {
    case "open":
      return accepting ? "Open" : "Closed, settling";
    case "collected":
      return "Funded";
    case "partial":
      return "Funded, still collecting";
    case "expired":
      return "Ended short of its goal";
    case "cancelled":
      return "Cancelled";
    default:
      return String(status);
  }
}
