import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "../lib/css";
import { nextTab, type TabItem } from "../lib/tabs";

export type { TabItem } from "../lib/tabs";

export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

interface TabsProps {
  /** What the tabs are, for screen readers: "Survey results". */
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

/**
 * A bar of tabs (the WAI-ARIA tabs pattern): one panel shows at a time; arrow keys, Home and End move between the tabs
 * that can be chosen, and choosing one shows its panel. Tabs whose content has not arrived are shown, dimmed, and
 * cannot be chosen. Pinned so it stays in view while its panel scrolls.
 */
export function Tabs({ label, items, selected, onSelect, idPrefix, pin = "page", className }: TabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>());

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
    <div className={cx("tabs", `tabs-${pin}`, className)} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
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
            tabIndex={on || (selected === null && !item.disabled) ? 0 : -1}
            onClick={() => {
              if (!item.disabled && !on) onSelect(item.id);
            }}
          >
            <span className="tab-label">{item.label}</span>
            {item.badge ? <span className="tab-badge mono">{item.badge}</span> : null}
          </button>
        );
      })}
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
