import type { MarkState } from "../lib/brand";
import { cx } from "../lib/css";
import type { Section, SectionId } from "../lib/sections";
import type { Theme } from "../state/theme";
import { AccountMenu } from "./AccountMenu";
import { BrandMark } from "./BrandMark";
import { EngineNote } from "./EngineNote";
import { ThemeToggle } from "./ThemeToggle";

interface TopBarProps {
  /** The mark follows the survey: where it stands, and how far along it is from 0 to 1. */
  mark: MarkState;
  progress: number;
  /** The survey's sections; none on the pages that are not the survey. */
  sections: readonly Section[];
  ready: readonly SectionId[];
  current: SectionId | null;
  theme: Theme;
  onToggleTheme: () => void;
}

export function TopBar({ mark, progress, sections, ready, current, theme, onToggleTheme }: TopBarProps) {
  return (
    <header className="bar">
      <a className="mark" href="/" aria-label="Walk-in, start over">
        <BrandMark state={mark} progress={progress} />
        <span className="mark-word">Walk-in</span>
      </a>
      {sections.length ? (
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
      ) : (
        <span className="bar-gap" />
      )}
      <div className="bar-end">
        <AccountMenu />
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
      <EngineNote />
    </header>
  );
}
