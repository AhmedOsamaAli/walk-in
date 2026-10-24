import { ExampleBanner } from "../components/ExampleBanner";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { pageUrl, type PageRoute } from "../lib/routes";
import { kitExample, useExamples } from "../state/examples";
import { DossierPage } from "./DossierPage";
import { ExamplesPage } from "./ExamplesPage";
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

interface PageViewProps {
  route: PageRoute;
  /** "Survey your own storefront", from the examples and an example's pages: a fresh brief at "/". */
  onFresh: () => void;
}

function Shown({ route, onFresh }: PageViewProps) {
  switch (route.page) {
    case "places":
      return <PlacesPage />;
    case "privacy":
      return <PrivacyPage />;
    case "examples":
      return <ExamplesPage onFresh={onFresh} />;
    case "kit":
      return <KitPage token={route.token} />;
    case "dossier":
      return <DossierPage token={route.token} />;
  }
}

/**
 * The page an address asks for, each in a boundary of its own so nothing carries over from one page to the next. An
 * example's kit and its report say they are an example, above the page and off its paper.
 */
export function PageView({ route, onFresh }: PageViewProps) {
  const { list } = useExamples();
  const example = route.page === "kit" || route.page === "dossier" ? kitExample(list, route.token) : null;
  return (
    <>
      {example ? <ExampleBanner example={example} onFresh={onFresh} page /> : null}
      <ErrorBoundary key={pageUrl(route)} fallback={<Broken />}>
        <Shown route={route} onFresh={onFresh} />
      </ErrorBoundary>
    </>
  );
}
