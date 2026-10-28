/* PayPal's JS SDK v6, loaded from PayPal by a script tag (never bundled), only where a pledge can be made: the core
   script, then one instance for the server's client id with the PayPal button's component. The types are the few
   parts of @paypal/paypal-js's "sdk-v6" types this app uses. */
import type { PayPalConfig } from "../api/founders";

/** What PayPal hands back once the supporter approved the order. */
export interface PayPalApproval {
  orderId: string;
  payerId?: string;
}

export interface PayPalFailure {
  code?: string;
  message?: string;
  isRecoverable?: boolean;
}

export interface PayPalSessionCallbacks {
  onApprove: (data: PayPalApproval) => Promise<void>;
  onCancel: (data: { orderId?: string }) => void;
  onError: (error: PayPalFailure) => void;
}

/** One way through PayPal: started on a click, with the order the server is creating. */
export interface PayPalSession {
  start: (options: { presentationMode: "auto" }, order: Promise<{ orderId: string }>) => Promise<unknown>;
  cancel: () => void;
  destroy: () => void;
}

export interface PayPalSdk {
  findEligibleMethods: (options: { currencyCode: string }) => Promise<{ isEligible: (method: string) => boolean }>;
  createPayPalOneTimePaymentSession: (callbacks: PayPalSessionCallbacks) => PayPalSession;
}

interface PayPalNamespace {
  createInstance: (options: {
    clientId: string;
    components: string[];
    pageType: string;
    locale: string;
  }) => Promise<PayPalSdk>;
}

/** The core script for each of PayPal's environments. */
export const SDK_URLS: Record<PayPalConfig["environment"], string> = {
  sandbox: "https://www.sandbox.paypal.com/web-sdk/v6/core",
  live: "https://www.paypal.com/web-sdk/v6/core",
};

const LOAD_TIMEOUT_MS = 20_000;

/** The SDK's namespace, when `value` is one. */
export function namespaceOf(value: unknown): PayPalNamespace | null {
  return typeof value === "object" && value !== null && "createInstance" in value && typeof value.createInstance === "function"
    ? (value as PayPalNamespace)
    : null;
}

const pageNamespace = () => namespaceOf((window as { paypal?: unknown }).paypal);

const cores = new Map<string, Promise<PayPalNamespace>>();

/** The core script, added to the page once; rejects when it fails, or loads without defining `paypal`. */
function loadCore(src: string): Promise<PayPalNamespace> {
  const known = cores.get(src);
  if (known) return known;
  let script: HTMLScriptElement | null = null;
  const loading = new Promise<PayPalNamespace>((resolve, reject) => {
    const present = pageNamespace();
    if (present) {
      resolve(present);
      return;
    }
    const tag = document.createElement("script");
    script = tag;
    const fail = () => {
      window.clearTimeout(timer);
      reject(new Error("PayPal could not load."));
    };
    const timer = window.setTimeout(fail, LOAD_TIMEOUT_MS);
    tag.src = src;
    tag.async = true;
    tag.addEventListener("load", () => {
      window.clearTimeout(timer);
      const loaded = pageNamespace();
      if (loaded) resolve(loaded);
      else fail();
    });
    tag.addEventListener("error", fail);
    document.head.append(tag);
  });
  cores.set(src, loading);
  // A load that failed can be tried again, with a fresh script.
  loading.catch(() => {
    cores.delete(src);
    script?.remove();
  });
  return loading;
}

const instances = new Map<string, Promise<PayPalSdk>>();

/** The SDK instance for the server's PayPal app, made once per page and environment. */
export function payPalSdk(paypal: PayPalConfig): Promise<PayPalSdk> {
  const clientId = paypal.client_id ?? "";
  const key = `${paypal.environment}:${clientId}`;
  const known = instances.get(key);
  if (known) return known;
  const made = loadCore(SDK_URLS[paypal.environment]).then((namespace) =>
    namespace.createInstance({ clientId, components: ["paypal-payments"], pageType: "checkout", locale: "en-US" }),
  );
  instances.set(key, made);
  made.catch(() => {
    instances.delete(key);
  });
  return made;
}
