import { useEffect, useState } from "react";
import type { Intent } from "../api/types";

export type SectionId = "s-log" | "s-block" | "s-gaps" | "s-verdict" | "s-improve" | "s-concepts" | "s-taste";

export interface Section {
  id: SectionId;
  /** "01", "02"…: its place in this survey. */
  no: string;
  label: string;
}

const NAMES: Record<SectionId, string> = {
  "s-log": "Log",
  "s-block": "Block",
  "s-gaps": "Gaps",
  "s-verdict": "Verdict",
  "s-improve": "Moves",
  "s-concepts": "Concepts",
  "s-taste": "Taste",
};

const ORDER: Record<Intent, readonly SectionId[]> = {
  explore: ["s-log", "s-block", "s-gaps", "s-concepts", "s-taste"],
  open: ["s-log", "s-block", "s-gaps", "s-verdict", "s-concepts", "s-taste"],
  improve: ["s-log", "s-block", "s-gaps", "s-improve", "s-taste"],
};

/** The sections a survey of this intent has, numbered in page order. */
export function sectionsFor(intent: Intent): Section[] {
  return ORDER[intent].map((id, index) => ({ id, no: String(index + 1).padStart(2, "0"), label: NAMES[id] }));
}

export function sectionNo(intent: Intent, id: SectionId): string {
  return sectionsFor(intent).find((section) => section.id === id)?.no ?? "";
}

/** The section in the middle of the viewport, among the sections that are on the page. */
export function useSectionSpy(ready: readonly SectionId[]): SectionId | null {
  const [current, setCurrent] = useState<SectionId | null>(null);
  const key = ready.join(" ");

  useEffect(() => {
    const ids = (key ? key.split(" ") : []) as SectionId[];
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = ids.find((section) => section === entry.target.id);
          if (entry.isIntersecting && id) setCurrent(id);
        }
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    for (const id of ids) {
      const section = document.getElementById(id);
      if (section) observer.observe(section);
    }
    return () => {
      observer.disconnect();
    };
  }, [key]);

  return current && ready.includes(current) ? current : null;
}
