import { cssVars, cx } from "../../lib/css";
import { progressShare } from "../../lib/founders";

interface ProgressBarProps {
  supporters: number;
  goal: number;
  funded: boolean;
  /** What the bar measures, for screen readers: "Neighbors backing Golden Hour". Without one, the bar only repeats
   * words beside it, and screen readers skip it. */
  label?: string;
  className?: string;
}

/** How many neighbors have joined toward the goal: the blue pen while it fills, the highlighter once it is met. */
export function ProgressBar({ supporters, goal, funded, label, className }: ProgressBarProps) {
  const style = cssVars({ "--p": progressShare({ supporters, goal }) });
  if (!label) {
    return (
      <span className={cx("fd-bar", funded && "funded", className)} aria-hidden="true" style={style}>
        <i />
      </span>
    );
  }
  return (
    <div
      className={cx("fd-bar", funded && "funded", className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={goal}
      aria-valuenow={Math.min(supporters, goal)}
      aria-valuetext={`${supporters} of ${goal} neighbors${funded ? ", goal met" : ""}`}
      style={style}
    >
      <i />
    </div>
  );
}
