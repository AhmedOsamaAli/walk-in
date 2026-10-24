import type { ClaimKind, LaunchPlan, TagShare } from "../api/types";

export const CLAIM_KINDS: Record<ClaimKind, string> = {
  only: "Only here",
  new: "New to the block",
  closer: "Closer to home",
  promise: "A promise",
};

/** "3 of 4 places": how much of the evidence a tag rests on. */
export function shareText({ places, of }: TagShare): string {
  return `${places} of ${of} place${of === 1 ? "" : "s"}`;
}

/** The names people near the site over-index on, by kind, leaving out the empty kinds. */
export function audienceRows(audience: LaunchPlan["audience"]): { title: string; names: string[] }[] {
  const rows = [
    { title: "Artists", names: audience.artists },
    { title: "Podcasts", names: audience.podcasts },
    { title: "Films & shows", names: audience.screen },
    { title: "Brands", names: audience.brands },
  ];
  return rows.filter((row) => row.names.length);
}

/** Whether there is anything to act on: a plan with no claim, audience or channel is left out. */
export function hasLaunchPlan(plan: LaunchPlan | null | undefined): plan is LaunchPlan {
  if (!plan) return false;
  return Boolean(plan.claims.length || plan.channels.length || plan.audience.crowd.length || audienceRows(plan.audience).length);
}

/** The plan's area in words, as the server names it ("30-minute drive"); plans made before drives were walks. */
export const areaText = (where: Pick<LaunchPlan["where"], "label" | "minutes">): string =>
  where.label ?? `${where.minutes}-minute walk`;

/**
 * How far around the site the audiences were read, as the plan's basis line says it ("Audiences are what people within
 * 6.469 km over-index on…"), to a tenth of a kilometre under 10: 1.5 km, or farther for a big drive. A plan that does
 * not say was read within 1.5 km.
 */
export function audienceReach(basis: string | null | undefined): string {
  const km = Number(/\bwithin (\d+(?:\.\d+)?) km\b/.exec(basis ?? "")?.[1]);
  if (!Number.isFinite(km) || km <= 0) return "1.5 km";
  return `${km < 10 ? String(Math.round(km * 10) / 10) : String(Math.round(km))} km`;
}

/** How far the area reaches: "556 m", or "14.2 km" from a kilometre on. */
export const reachText = (meters: number): string => (meters < 1000 ? `${meters} m` : `${(meters / 1000).toFixed(1)} km`);
