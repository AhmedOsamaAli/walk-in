/* Payments only: the launch kit, its dossier and the pledge page, as PageView shows them. Leaves with the payment UI. */
import type { PaymentRoute } from "../lib/routes";
import { DossierPage } from "./DossierPage";
import { KitPage } from "./KitPage";
import { PledgePage } from "./PledgePage";

/** The key that gives each kit, dossier and campaign a fresh page. */
export function paymentKey(route: PaymentRoute): string {
  return route.page === "pledge" ? `pledge:${route.id}` : `${route.page}:${route.token}`;
}

export function PaymentPage({ route }: { route: PaymentRoute }) {
  switch (route.page) {
    case "kit":
      return <KitPage token={route.token} />;
    case "dossier":
      return <DossierPage token={route.token} />;
    case "pledge":
      return <PledgePage id={route.id} withdraw={route.withdraw} />;
  }
}
