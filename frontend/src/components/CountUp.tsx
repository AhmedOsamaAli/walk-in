import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "../lib/motion";

interface CountUpProps {
  value: number;
  decimals?: number;
  className?: string;
}

/** A number that counts up from zero when it appears. */
export function CountUp({ value, decimals = 0, className }: CountUpProps) {
  const element = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    // Writes go to React's own text node, so React and the animation never fight over the element.
    const text = element.current?.firstChild;
    if (!text) return;
    const target = Number.isFinite(value) ? value : 0;
    if (prefersReducedMotion()) {
      text.nodeValue = target.toFixed(decimals);
      return;
    }
    const start = performance.now();
    let frame = requestAnimationFrame(function tick(now: number) {
      const t = Math.min(1, (now - start) / 1100);
      text.nodeValue = (target * (1 - (1 - t) ** 3)).toFixed(decimals);
      if (t < 1) frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [value, decimals]);

  return (
    <span ref={element} className={className}>
      {(0).toFixed(decimals)}
    </span>
  );
}
