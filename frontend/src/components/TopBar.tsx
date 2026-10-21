import { cssVars, cx } from "../lib/css";
import type { Section, SectionId } from "../lib/sections";
import type { Theme } from "../state/theme";
import { ThemeToggle } from "./ThemeToggle";

interface TopBarProps {
  /** How full the mark's square is, from 0 to 1: the survey's progress. */
  fill: number;
  sections: readonly Section[];
  ready: readonly SectionId[];
  current: SectionId | null;
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({ fill, sections, ready, current, theme, onToggleTheme }: TopBarProps) {
  return (
    <header className="bar">
      <a className="mark" href="/" aria-label="Blank Space, start over">
        <span className="mark-square" aria-hidden="true">
          <i style={cssVars({ "--p": Math.max(0.04, Math.min(1, fill)) })} />
        </span>
        <span className="mark-word">Blank Space</span>
      </a>
      <nav className="bar-nav mono" aria-label="Survey sections">
        {sections.map(({ id, no, label }) => {
          const available = ready.includes(id);
          return (
            <a
              key={id}
              href={`#${id}`}
              className={cx(available && "ready", current === id && "current")}
              aria-disabled={available ? undefined : true}
              aria-current={current === id ? "location" : undefined}
              tabIndex={available ? undefined : -1}
            >
              {no} {label}
            </a>
          );
        })}
      </nav>
      <div className="bar-end">
        <span className="bar-meta mono">
          Taste data{" "}
          <a href="https://www.qloo.com" target="_blank" rel="noopener">
            Qloo
          </a>
        </span>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
    </header>
  );
}
