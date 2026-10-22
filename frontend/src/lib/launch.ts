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
