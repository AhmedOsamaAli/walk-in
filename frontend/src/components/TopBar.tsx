import { useEffect, useRef, useState } from "react";
import { markLabel, replays, type MarkState } from "../lib/brand";
import { prefersReducedMotion } from "../lib/motion";
import { isPlainClick, type HomeMove } from "../lib/navigation";
import { BRIEF_URL, EXAMPLES_URL } from "../lib/routes";
import type { Theme } from "../state/theme";
import { AccountMenu } from "./AccountMenu";
import { BrandMark } from "./BrandMark";
import { EngineNote } from "./EngineNote";
import { Link } from "./Link";
import { ThemeToggle } from "./ThemeToggle";

interface TopBarProps {
  /** The mark follows the survey: where it stands, and how far along it is from 0 to 1. */
  mark: MarkState;
  progress: number;
  /** What a click on the mark does from here; the app does it in place, without reloading the page. */
  home: HomeMove;
  onHome: () => void;
  theme: Theme;
  onToggleTheme: () => void;
  /** The map fills the screen over the bar: nothing on it can be reached meanwhile. */
  inert?: boolean;
  /** The finished examples' link: on every page ("current" on their own), and gone once none turn out to exist. */
  examples?: "link" | "current" | null;
}

/** The mark, the examples, the account and the theme. A survey's own navigation is its tabs, pinned under this bar. */
export function TopBar({
  mark,
  progress,
  home,
  onHome,
  theme,
  onToggleTheme,
  inert = false,
  examples = "link",
}: TopBarProps) {
  const [replay, setReplay] = useState(0);
  /** When the last walk-in started, on performance.now()'s clock; the first plays as the page loads. */
  const playedAt = useRef(0);

  useEffect(() => {
    playedAt.current = performance.now();
  }, []);

  function play(cause: "click" | "preview") {
    const now = performance.now();
    if (!replays(cause, prefersReducedMotion(), now - playedAt.current)) return;
    playedAt.current = now;
    setReplay((count) => count + 1);
  }

  return (
    <header className="bar" inert={inert}>
      <a
        className="mark"
        href={BRIEF_URL}
        aria-label={markLabel(home)}
        onPointerEnter={(event) => {
          // A mouse hover previews the walk; a tap on a phone plays it with its click instead.
          if (event.pointerType === "mouse") play("preview");
        }}
        onFocus={(event) => {
          if (event.currentTarget.matches(":focus-visible")) play("preview");
        }}
        onClick={(event) => {
          if (!isPlainClick(event)) return;
          event.preventDefault();
          play("click");
          onHome();
        }}
      >
        <BrandMark state={mark} progress={progress} replay={replay} />
        <span className="mark-word">Walk-in</span>
      </a>
      <span className="bar-gap" />
      <div className="bar-end">
        {examples ? (
          <Link
            className="bar-link bar-examples mono"
            href={EXAMPLES_URL}
            aria-current={examples === "current" ? "page" : undefined}
            title="Finished surveys anyone can open, with their launch kit and report"
          >
            <span className="bar-examples-verb">See</span>
            <span>examples</span>
          </Link>
        ) : null}
        <AccountMenu />
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
      <EngineNote />
    </header>
  );
}
