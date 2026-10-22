import { useEffect, useState } from "react";

/** The time now, ticking every `interval` ms while `active`, for countdowns and elapsed times. */
export function useNow(interval: number, active = true): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, interval);
    return () => {
      window.clearInterval(timer);
    };
  }, [interval, active]);
  return now;
}
