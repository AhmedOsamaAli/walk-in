import { useEffect, useState } from "react";

export const SECTIONS = [
  { id: "s-log", label: "01 Log" },
  { id: "s-block", label: "02 Block" },
  { id: "s-gaps", label: "03 Gaps" },
  { id: "s-concepts", label: "04 Concepts" },
  { id: "s-taste", label: "05 Taste" },
] as const;

export type SectionId = (typeof SECTIONS)[number]["id"];

/** The section in the middle of the viewport, among the sections that are on the page. */
export function useSectionSpy(ready: readonly SectionId[]): SectionId | null {
  const [current, setCurrent] = useState<SectionId | null>(null);
  const key = ready.join(" ");

  useEffect(() => {
    const ids = key ? key.split(" ") : [];
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = SECTIONS.find((section) => section.id === entry.target.id)?.id;
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
