import type { Theme } from "../state/theme";

interface ThemeToggleProps {
  theme: Theme;
  onToggle: () => void;
}

export function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  return (
    <button className="theme-toggle" type="button" onClick={onToggle} aria-label={label} title={label}>
      {theme === "dark" ? (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.6M12 18.9v2.6M2.5 12h2.6M18.9 12h2.6M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M19.5 14.6A8 8 0 0 1 9.4 4.5a8 8 0 1 0 10.1 10.1Z" />
        </svg>
      )}
    </button>
  );
}
