import { createContext, useCallback, useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { withViewTransition } from "../lib/motion";

export type Theme = "light" | "dark";

/** The theme on screen, for the parts drawn by others (Google's and PayPal's buttons) that must be told it. */
export const ThemeContext = createContext<Theme>("light");

/** Shared with public/theme.js, which applies the theme before the first paint. */
const STORAGE_KEY = "walk-in-theme";
const THEME_COLORS: Record<Theme, string> = { light: "#f5f4ef", dark: "#0d111c" };

function savedTheme(): Theme | null {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    return null;
  }
}

function saveTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Private browsing can refuse storage; the choice then lasts for this page only.
  }
}

function appliedTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme]);
}

/** The light or dark theme: the system's until the user picks one, which is then remembered. */
export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(appliedTheme);

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => {
      if (savedTheme()) return;
      const next: Theme = query.matches ? "dark" : "light";
      applyTheme(next);
      setTheme(next);
    };
    query.addEventListener("change", follow);
    return () => {
      query.removeEventListener("change", follow);
    };
  }, []);

  const toggleTheme = useCallback(() => {
    const next: Theme = appliedTheme() === "dark" ? "light" : "dark";
    saveTheme(next);
    withViewTransition(() => {
      applyTheme(next);
      flushSync(() => {
        setTheme(next);
      });
    });
  }, []);

  return { theme, toggleTheme };
}
