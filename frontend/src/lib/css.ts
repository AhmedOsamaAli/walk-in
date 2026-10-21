import type { CSSProperties } from "react";

/** Inline custom properties, for values that change per element. */
export function cssVars(values: Record<`--${string}`, string | number>): CSSProperties {
  return values;
}

/** Joins the truthy class names. */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}
