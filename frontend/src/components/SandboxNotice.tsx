import { cx } from "../lib/css";

interface SandboxNoticeProps {
  /** Where a judge pays or pledges: points to the test buyer's details too. */
  judges?: boolean;
  className?: string;
}

/** Shown wherever money appears while PayPal runs in its sandbox. */
export function SandboxNotice({ judges = false, className }: SandboxNoticeProps) {
  return (
    <p className={cx("sandbox", className)}>
      <span className="sandbox-tag mono">Test mode:</span> PayPal sandbox, no real money
      {judges ? <span className="sandbox-judges">Judges: test buyer details are in the README</span> : null}
    </p>
  );
}
