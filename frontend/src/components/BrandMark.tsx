import { useEffect, useId, useState } from "react";
import { cssVars, cx } from "../lib/css";
import { litSteps, MARK_STEPS, type MarkState } from "../lib/brand";

/** Where each footstep falls on the way to the door: the ball of the foot, then the heel behind it. */
const STEPS = [
  { ball: [4.6, 30.8], heel: [1.6, 30.8] },
  { ball: [9, 34.2], heel: [6, 34.2] },
  { ball: [13.4, 30.8], heel: [10.4, 30.8] },
  { ball: [17.8, 34.2], heel: [14.8, 34.2] },
] as const;
/** How long the opening walk plays, in ms, before the mark follows the survey's state. */
const INTRO_MS = 2000;

/**
 * Footsteps that end at a door. On the brief the door stands open, swung out on its hinge, with light spilling onto
 * the sidewalk. A survey closes it and lights one step per fifth of its progress, the next one pulsing; at the door,
 * while the agent works, the door stands ajar with the light glowing; it swings open when the survey is done.
 */
export function BrandMark({ state, progress }: { state: MarkState; progress: number }) {
  const [intro, setIntro] = useState(true);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setIntro(false);
    }, INTRO_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, []);
  const lit = litSteps(state, progress);
  const atDoor = state === "walking" && lit === MARK_STEPS;
  const spill = `bm-spill${useId().replace(/[^\w-]/g, "")}`;

  return (
    <svg
      className={cx("brand-mark", intro && "intro")}
      data-state={state}
      data-at-door={atDoor ? "" : undefined}
      viewBox="0 0 40 40"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={spill} x1="0" y1="0" x2="0" y2="1">
          <stop className="bm-spill-near" offset="0" />
          <stop className="bm-spill-far" offset="1" />
        </linearGradient>
      </defs>
      <polygon className="bm-spill" points="22.5,33.5 32.5,33.5 36,39 19,39" fill={`url(#${spill})`} />
      <path className="bm-ink" d="M20.5 33.5H39" />
      {STEPS.map(({ ball, heel }, index) => (
        <g
          key={ball[0]}
          className="bm-step"
          data-lit={index < lit ? "" : undefined}
          data-next={state === "walking" && index === lit ? "" : undefined}
          style={cssVars({ "--i": index })}
        >
          <ellipse cx={ball[0]} cy={ball[1]} rx="1.7" ry="1.3" />
          <circle cx={heel[0]} cy={heel[1]} r=".95" />
        </g>
      ))}
      <rect className="bm-light" x="22.5" y="9.5" width="10" height="23" />
      <g className="bm-shut">
        <rect className="bm-leaf" x="22.5" y="9.5" width="10" height="23" />
        <rect className="bm-pane" x="24.6" y="11.6" width="5.8" height="8.4" rx=".6" />
        <circle className="bm-knob" cx="24.4" cy="22" r=".9" />
      </g>
      <rect className="bm-ink" x="21.5" y="8.5" width="12" height="25" rx="1" />
      <g className="bm-open">
        <polygon className="bm-leaf" points="33.5,9.5 38.6,7.2 38.6,35.2 33.5,32.5" />
        <polygon className="bm-pane" points="34.5,11.7 37.6,10.4 37.6,18.6 34.5,19.6" />
        <circle className="bm-knob" cx="37.7" cy="22.4" r=".8" />
      </g>
    </svg>
  );
}
