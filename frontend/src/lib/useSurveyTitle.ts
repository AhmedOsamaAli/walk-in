import { useEffect, useRef } from "react";
import type { SurveyStatus } from "../state/survey";
import { APP_TITLE, tabTitle } from "./journey";

/**
 * The survey in the tab's title, for an owner waiting in another tab (lib/journey.ts words it): "Surveying…" while it
 * runs; when it ends while the tab is hidden, how it ended, until the owner comes back; the app's name otherwise. A
 * survey that was already over when it appeared here changes nothing.
 */
export function useSurveyTitle(status: SurveyStatus): void {
  /** It ran on this page, so its end is news. */
  const ran = useRef(false);

  useEffect(() => {
    if (status === "running") ran.current = true;
    const unseen = ran.current && status !== "running" && document.hidden;
    document.title = tabTitle(status, unseen);
    const back = () => {
      if (document.hidden) return;
      document.title = APP_TITLE;
      document.removeEventListener("visibilitychange", back);
    };
    if (unseen) document.addEventListener("visibilitychange", back);
    return () => {
      document.removeEventListener("visibilitychange", back);
      document.title = APP_TITLE;
    };
  }, [status]);
}
