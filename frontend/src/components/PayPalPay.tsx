import { PayPalButtons, PayPalScriptProvider, usePayPalScriptReducer, type ReactPayPalScriptOptions } from "@paypal/react-paypal-js";
import { use, useMemo, useRef } from "react";
import type { PayPalConfig } from "../api/commerce";
import { ThemeContext } from "../state/theme";

/** What a payment ended in, for the page to say. */
export type PayNote = { tone: "info" | "error"; text: string } | null;

interface PayPalPayProps {
  paypal: PayPalConfig;
  /**
   * "capture" pays at once (the launch kit); "authorize" only holds the money (a pledge). The SDK's options must match
   * the order's intent, so each loads PayPal under its own namespace.
   */
  intent: "capture" | "authorize";
  /** What the buttons do, for screen readers: "Pay for the launch kit with PayPal". */
  label: string;
  /** Creates the order on the server; reports its own failure through `onNote` before rejecting. */
  createOrder: () => Promise<string>;
  /** Completes the approved order on the server; "retry" when the payment method was declined and PayPal may restart. */
  approve: (orderId: string) => Promise<"done" | "retry">;
  onNote: (note: PayNote) => void;
}

const NAMESPACES = { capture: "paypalCheckout", authorize: "paypalPledge" } as const;

function Buttons({ intent, label, createOrder, approve, onNote }: Omit<PayPalPayProps, "paypal">) {
  const [{ isPending, isRejected }] = usePayPalScriptReducer();
  const theme = use(ThemeContext);
  // A failure the page already explained must not be overwritten by PayPal's generic error that follows it.
  const explained = useRef(false);

  if (isRejected) {
    return (
      <p className="pay-note" data-tone="error" role="alert">
        PayPal could not load. Check your connection, or allow paypal.com if a blocker stops it, then reload the page.
      </p>
    );
  }
  return (
    <div className="pay-buttons" role="group" aria-label={label} aria-busy={isPending}>
      {isPending ? <div className="sk pay-wait" aria-hidden="true" /> : null}
      <PayPalButtons
        style={{
          layout: "vertical",
          shape: "pill",
          color: theme === "dark" ? "white" : "gold",
          height: 48,
          label: intent === "capture" ? "pay" : "paypal",
          tagline: false,
        }}
        forceReRender={[theme, intent]}
        createOrder={async () => {
          explained.current = false;
          onNote(null);
          try {
            return await createOrder();
          } catch (error) {
            explained.current = true;
            throw error;
          }
        }}
        onApprove={async (data, actions) => {
          explained.current = true;
          const outcome = await approve(data.orderID);
          explained.current = false;
          // A declined card can be swapped for another way to pay without starting over.
          if (outcome === "retry") {
            actions.restart();
          }
        }}
        onCancel={() => {
          onNote({ tone: "info", text: "Payment cancelled: nothing was charged." });
        }}
        onError={() => {
          if (explained.current) return;
          onNote({ tone: "error", text: "PayPal could not finish the payment, so nothing was charged. Try again." });
        }}
      />
    </div>
  );
}

/** PayPal's buttons, loaded with the options this kind of payment needs. */
export function PayPalPay({ paypal, intent, ...rest }: PayPalPayProps) {
  const options = useMemo<ReactPayPalScriptOptions>(
    () => ({
      clientId: paypal.client_id ?? "",
      currency: paypal.currency,
      intent,
      // Kit orders are paid on PayPal's page ("Pay Now"); a pledge only continues to a hold ("Continue").
      commit: intent === "capture",
      components: "buttons",
      disableFunding: "paylater,venmo",
      dataNamespace: NAMESPACES[intent],
      ...(paypal.environment === "sandbox" || paypal.environment === "production" ? { environment: paypal.environment } : {}),
    }),
    [paypal.client_id, paypal.currency, paypal.environment, intent],
  );
  return (
    <PayPalScriptProvider options={options}>
      <Buttons intent={intent} {...rest} />
    </PayPalScriptProvider>
  );
}
