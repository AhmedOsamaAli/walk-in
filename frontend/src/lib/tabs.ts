/** A tab a tab bar shows: its id (its panel's too), its label, and whether its content has arrived yet. */
export interface TabItem {
  id: string;
  label: string;
  /** Shown but not selectable: its content has not arrived yet (a survey still running). */
  disabled?: boolean;
  /** Its content is on its way (a survey still running): the tab says so, beside its dimmed label. */
  pending?: boolean;
  /** A short count or mark after the label, such as "3". */
  badge?: string | null;
  /** One short line of what the tab shows, said on the way in from the tab before (TabPager). */
  teaser?: string;
}

/** The ids of a tab bar's tabs and panels, from the prefix they share: "kit-tab-poster", "kit-panel-poster". */
export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

/**
 * The tab a key moves to (the WAI-ARIA tabs pattern, a horizontal bar): the next or previous selectable tab, wrapping
 * round, or the first or last; null for any other key, or when no other tab can be selected.
 */
export function nextTab(items: readonly TabItem[], current: string, key: string): string | null {
  const open = items.filter((item) => !item.disabled);
  if (!open.length) return null;
  const at = open.findIndex((item) => item.id === current);
  let target: TabItem | undefined;
  if (key === "ArrowRight") target = open[(at + 1) % open.length];
  else if (key === "ArrowLeft") target = open[(at - 1 + open.length) % open.length];
  else if (key === "Home") target = open[0];
  else if (key === "End") target = open.at(-1);
  return target && target.id !== current ? target.id : null;
}

/** The tab to show: the one asked for while it can be shown, else the first that can; null when none can yet. */
export function shownTab(items: readonly TabItem[], wanted: string | null): string | null {
  const open = items.filter((item) => !item.disabled);
  return open.find((item) => item.id === wanted)?.id ?? open[0]?.id ?? null;
}

export interface Pager {
  /** The tab before, to go back to; null on the first. */
  previous: TabItem | null;
  /** The tab after; after the last, the first, to start over from (`wraps`). Null when there is no other tab. */
  next: TabItem | null;
  wraps: boolean;
}

/**
 * The ways out of a panel at its foot, so the tabs read in order like pages: back to the tab before, on to the tab
 * after, and from the last back to the first. Tabs whose content has not arrived are passed over.
 */
export function pagerOf(items: readonly TabItem[], current: string): Pager {
  const open = items.filter((item) => !item.disabled);
  const at = open.findIndex((item) => item.id === current);
  if (at === -1 || open.length < 2) return { previous: null, next: null, wraps: false };
  const previous = at > 0 ? (open[at - 1] ?? null) : null;
  const after = open[at + 1];
  if (after) return { previous, next: after, wraps: false };
  return { previous, next: open[0] ?? null, wraps: true };
}
