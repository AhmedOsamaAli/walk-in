import { useEffect, useRef } from "react";
import { cssVars } from "../lib/css";
import { useNow } from "../lib/useNow";
import { engine, useEngine, type EngineNote as Note } from "../state/engine";

/** What a screen reader hears as the note changes: each change once, never the seconds. */
const SAID: Record<Note, string> = {
  none: "",
  waking: "Waking the survey engine. It naps when nobody's around; waking takes about 30 seconds.",
  ready: "The survey engine is ready.",
  leaving: "The survey engine is ready.",
  asleep: "The survey engine is still asleep. Try again to give it another nudge.",
};

/** The seconds so far, and a track that creeps on toward the end without claiming to know when it comes. */
function Waking({ since }: { since: number }) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return (
    <>
      <span className="wake-time mono" role="timer">
        {seconds} s
      </span>
      <span className="wake-track" aria-hidden="true">
        <i style={cssVars({ "--p": 1 - Math.exp(-seconds / 25) })} />
      </span>
    </>
  );
}

/** A headline, and the rest of the sentence after a dot; a narrow note sets the rest on a line of its own. */
function Words({ lead, rest }: { lead: string; rest?: string }) {
  return (
    <p className="wake-text">
      <b>{lead}</b>
      {rest ? (
        <>
          <span className="wake-sep"> · </span>
          <span className="wake-more">{rest}</span>
        </>
      ) : null}
    </p>
  );
}

/**
 * Hung under the top bar while the backend wakes from a nap: what is happening and for how long so far, then "Ready"
 * as it fades away; or, when it does not wake, a way to try again. What it hangs over moves down to make room for it
 * (--wake-h, styles/wake.css), so it never covers the page.
 */
export function EngineNote() {
  const { note, since } = useEngine();
  const band = useRef<HTMLDivElement>(null);
  const retried = useRef(false);
  const done = note === "ready" || note === "leaving";
  const shown = note === "waking" || note === "ready" || note === "asleep";

  useEffect(() => {
    // Try again takes its button away: focus stays on the note rather than falling back to the top of the page.
    if (note === "waking" && retried.current) {
      retried.current = false;
      band.current?.focus({ preventScroll: true });
    }
  }, [note]);

  useEffect(() => {
    const element = band.current;
    if (!shown || !element) return;
    const root = document.documentElement;
    // The room it takes only grows while it shows, so "Ready" on one line does not pull the page up before it goes.
    let tallest = 0;
    const observer = new ResizeObserver(() => {
      tallest = Math.max(tallest, element.offsetHeight);
      root.style.setProperty("--wake-h", `${tallest}px`);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--wake-h");
    };
  }, [shown]);

  return (
    <>
      <div ref={band} className="wake" data-note={note} hidden={note === "none"} tabIndex={-1}>
        <span className="wake-mark" aria-hidden="true">
          {done ? "✓" : null}
        </span>
        {note === "asleep" ? (
          <Words lead="The survey engine is still asleep" rest="give it another nudge" />
        ) : done ? (
          <Words lead="Ready" />
        ) : (
          <Words lead="Waking the survey engine" rest={"it naps when nobody's around, about 30\u00a0s"} />
        )}
        {note === "waking" ? <Waking since={since} /> : null}
        {done ? (
          <span className="wake-track" aria-hidden="true">
            <i style={cssVars({ "--p": 1 })} />
          </span>
        ) : null}
        {note === "asleep" ? (
          <button
            type="button"
            className="wake-retry mono"
            onClick={() => {
              retried.current = true;
              engine.retry();
            }}
          >
            Try again
          </button>
        ) : null}
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {SAID[note]}
      </p>
    </>
  );
}
