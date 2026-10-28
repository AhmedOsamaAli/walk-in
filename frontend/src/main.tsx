import "./styles/index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { CrashScreen } from "./components/CrashScreen";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { currentRoute } from "./lib/routes";
import { preloadRoute } from "./preload";

const root = document.getElementById("root");
if (!root) throw new Error("The page has no #root element.");

// What the address opens on starts loading with the app rather than after its first render, side by side: a survey's
// view, the map and the survey's record; a kit's page and the kit.
preloadRoute(currentRoute());

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary fallback={<CrashScreen />}>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
