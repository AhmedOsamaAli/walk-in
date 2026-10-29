import { cx } from "../../lib/css";

/** Wherever money appears while PayPal runs in its sandbox: "Test mode: PayPal sandbox, no real money." */
export function SandboxNotice({ className }: { className?: string }) {
  return (
    <p className={cx("sandbox", className)}>
      <span className="sandbox-tag mono">Test mode:</span> PayPal sandbox, no real money.
    </p>
  );
}
