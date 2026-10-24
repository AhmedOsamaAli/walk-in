import { ErrorBoundary } from "../components/ErrorBoundary";
import { pageUrl, type PageRoute } from "../lib/routes";
import { DossierPage } from "./DossierPage";
import { KitPage } from "./KitPage";
import { PlacesPage } from "./PlacesPage";
import { PrivacyPage } from "./PrivacyPage";

function Broken() {
  return (
    <main className="page" id="main">
      <div className="page-sheet">
        <p className="page-alert" role="alert">
          This page could not be shown. Reload it to try again.
        </p>
      </div>
    </main>
  );
}

function Shown({ route }: { route: PageRoute }) {
  switch (route.page) {
    case "places":
      return <PlacesPage />;
    case "privacy":
      return <PrivacyPage />;
    case "kit":
      return <KitPage token={route.token} />;
    case "dossier":
      return <DossierPage token={route.token} />;
  }
}

/** The page an address asks for, each in a boundary of its own so nothing carries over from one page to the next. */
export function PageView({ route }: { route: PageRoute }) {
  return (
    <ErrorBoundary key={pageUrl(route)} fallback={<Broken />}>
      <Shown route={route} />
    </ErrorBoundary>
  );
}
