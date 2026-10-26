import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "../lib/css";
import { nextTab, pagerOf, type TabItem } from "../lib/tabs";

export type { TabItem } from "../lib/tabs";

export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

interface TabsProps {
  /** What the tabs are, said before them and to screen readers: "Results", "Your kit". */
  label: string;
  items: TabItem[];
  selected: string | null;
  onSelect: (id: string) => void;
  /** Shared by the tabs and their panels' ids, so several tab bars can live on one page. */
  idPrefix: string;
  /** "page": pinned under the top bar while the page scrolls; "sheet": pinned at the top of a scrolling sheet. */
  pin?: "page" | "sheet";
  className?: string;
}

/** Marks which ends of the track have tabs out of sight, for the fades that say there is more (styles/tabs.css). */
function markOverflow(track: HTMLElement): void {
  track.toggleAttribute("data-more-start", track.scrollLeft > 1);
  track.toggleAttribute("data-more-end", track.scrollLeft + track.clientWidth < track.scrollWidth - 1);
}

/**
 * A bar of tabs (the WAI-ARIA tabs pattern) that looks like what it is: a label, then a segmented control whose chosen
 * tab is filled. One panel shows at a time; arrow keys, Home and End move between the tabs that can be chosen. Tabs
 * whose content has not arrived are shown, dimmed, and cannot be chosen; one on its way says so. Wider than the screen,
 * the control scrolls sideways, fades at the side with more, and keeps the chosen tab in view. Pinned so it stays in
 * view while its panel scrolls.
 */
export function Tabs({ label, items, selected, onSelect, idPrefix, pin = "page", className }: TabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const track = useRef<HTMLDivElement>(null);
  const labelId = `${idPrefix}-tabs-label`;

  useLayoutEffect(() => {
    const node = track.current;
    if (!node) return;
    const update = () => {
      markOverflow(node);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    node.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      node.removeEventListener("scroll", update);
    };
  }, []);

  // The chosen tab in view along the track, clear of its fades.
  useLayoutEffect(() => {
    const node = track.current;
    const chosen = selected === null ? undefined : refs.current.get(selected);
    if (!node || !chosen) return;
    const edge = chosen.getBoundingClientRect();
    const view = node.getBoundingClientRect();
    if (edge.left < view.left + 4) node.scrollLeft += edge.left - view.left - 32;
    else if (edge.right > view.right - 4) node.scrollLeft += edge.right - view.right + 32;
    markOverflow(node);
  }, [selected, items.length]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (selected === null) return;
    const target = nextTab(items, selected, event.key);
    if (target === null) return;
    event.preventDefault();
    onSelect(target);
    // The bar is pinned: moving focus along it must not scroll the page.
    refs.current.get(target)?.focus({ preventScroll: true });
  }

  return (
    <div className={cx("tabs", `tabs-${pin}`, className)}>
      <span className="tabs-label mono" id={labelId}>
        {label}
      </span>
      <div ref={track} className="tabs-track" role="tablist" aria-labelledby={labelId} onKeyDown={onKeyDown}>
        {items.map((item) => {
          const on = item.id === selected;
          return (
            <button
              key={item.id}
              ref={(node) => {
                if (node) refs.current.set(item.id, node);
                else refs.current.delete(item.id);
              }}
              className="tab"
              type="button"
              role="tab"
              id={tabId(idPrefix, item.id)}
              aria-selected={on}
              aria-controls={panelId(idPrefix, item.id)}
              aria-disabled={item.disabled ? true : undefined}
              title={item.pending ? "On its way" : undefined}
              tabIndex={on || (selected === null && !item.disabled) ? 0 : -1}
              onClick={() => {
                if (!item.disabled && !on) onSelect(item.id);
              }}
            >
              <span className="tab-label">{item.label}</span>
              {item.badge ? <span className="tab-badge mono">{item.badge}</span> : null}
              {item.pending ? (
                <>
                  <span className="tab-wait" aria-hidden="true" />
                  <span className="sr-only">, on its way</span>
                </>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface TabPanelProps {
  idPrefix: string;
  id: string;
  selected: boolean;
  children: ReactNode;
  className?: string;
}

/** A tab's panel: hidden while another tab is chosen, but kept, so what it holds (an open row) survives; on paper every
 * panel prints. */
export function TabPanel({ idPrefix, id, selected, children, className }: TabPanelProps) {
  return (
    <div
      className={cx("tab-panel", className)}
      role="tabpanel"
      id={panelId(idPrefix, id)}
      aria-labelledby={tabId(idPrefix, id)}
      hidden={!selected}
    >
      {children}
    </div>
  );
}

interface TabPagerProps {
  items: TabItem[];
  /** The tab whose panel this pager ends. */
  current: string;
  /** Shows a tab; the panel this pager is in hides, so focus should move into the one that shows. */
  onSelect: (id: string) => void;
  className?: string;
}

/**
 * A panel's last line, so the tabs read in order like pages: on to the next tab, filled, as the way forward; back to
 * the one before; from the last, back to the first.
 */
export function TabPager({ items, current, onSelect, className }: TabPagerProps) {
  const { previous, next, wraps } = pagerOf(items, current);
  if (!previous && !next) return null;
  return (
    <nav className={cx("tab-pager", className)} aria-label="Next and previous">
      {previous ? (
        <button
          type="button"
          className="tab-pager-back"
          onClick={() => {
            onSelect(previous.id);
          }}
        >
          <span aria-hidden="true">←</span> {previous.label}
        </button>
      ) : null}
      {next ? (
        <button
          type="button"
          className="tab-pager-next"
          onClick={() => {
            onSelect(next.id);
          }}
        >
          {wraps ? (
            `Back to ${next.label}`
          ) : (
            <>
              Next: {next.label} <span aria-hidden="true">→</span>
            </>
          )}
        </button>
      ) : null}
    </nav>
  );
}
