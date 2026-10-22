import { ErrorBoundary } from "../components/ErrorBoundary";
import { isPaymentRoute, type PageRoute } from "../lib/routes";
import { PaymentPage, paymentKey } from "./PaymentPages";
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

/** The page an address asks for, each in a boundary of its own so nothing carries over from one page to the next. */
export function PageView({ route }: { route: PageRoute }) {
  if (isPaymentRoute(route)) {
    return (
      <ErrorBoundary key={paymentKey(route)} fallback={<Broken />}>
        <PaymentPage route={route} />
      </ErrorBoundary>
    );
  }
  return (
    <ErrorBoundary key={route.page} fallback={<Broken />}>
      {route.page === "places" ? <PlacesPage /> : <PrivacyPage />}
    </ErrorBoundary>
  );
}
