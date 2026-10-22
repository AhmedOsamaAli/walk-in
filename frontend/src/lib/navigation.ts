import { createContext, use } from "react";

/** Moves the app to another of its addresses without reloading the page; `replace` keeps Back where it was. */
export type Navigate = (url: string, options?: { replace?: boolean }) => void;

export const NavigateContext = createContext<Navigate>((url) => {
  window.location.assign(url);
});

export function useNavigate(): Navigate {
  return use(NavigateContext);
}
