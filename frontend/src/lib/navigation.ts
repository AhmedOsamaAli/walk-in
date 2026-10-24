import { createContext, use } from "react";

/** Moves the app to another of its addresses without reloading the page; `replace` keeps Back where it was. */
export type Navigate = (url: string, options?: { replace?: boolean }) => void;

export const NavigateContext = createContext<Navigate>((url) => {
  window.location.assign(url);
});

export function useNavigate(): Navigate {
  return use(NavigateContext);
}

/** What the window shows, as the mark sees it: the brief, a survey's link loading, a survey, or another page. */
export type Showing = "brief" | "opening" | "survey" | "page";

/**
 * What the mark does when clicked. On the brief it goes back to the top and keeps the form ("top"); from a survey, or a
 * survey's link still loading, it starts over on a fresh brief as a reload of "/" did, the survey staying saved at its
 * link ("fresh"); from another page it shows the brief as it was left ("brief").
 */
export type HomeMove = "top" | "fresh" | "brief";

export function homeMove(showing: Showing): HomeMove {
  if (showing === "brief") return "top";
  if (showing === "page") return "brief";
  return "fresh";
}

interface ClickLike {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  defaultPrevented?: boolean;
}

/** A plain primary click, which the app handles in place; a modified or middle click opens the link as browsers do. */
export function isPlainClick(event: ClickLike): boolean {
  if (event.defaultPrevented || event.button !== 0) return false;
  return !(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey);
}
