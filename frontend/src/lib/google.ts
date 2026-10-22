/* Google Identity Services, loaded only where someone may sign in. Typed here as far as this app uses it. */

interface CredentialResponse {
  /** The ID token (a JWT) the server verifies. */
  credential: string;
  select_by?: string;
}

interface IdConfiguration {
  client_id: string;
  callback: (response: CredentialResponse) => void;
  auto_select?: boolean;
  cancel_on_tap_outside?: boolean;
  context?: "signin" | "signup" | "use";
  ux_mode?: "popup" | "redirect";
  itp_support?: boolean;
}

export interface GoogleButtonOptions {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape?: "rectangular" | "pill" | "circle" | "square";
  logo_alignment?: "left" | "center";
  /** In pixels, 200 to 400. */
  width?: number;
  /** The button's language; without it Google picks one from the browser or the visitor's location. */
  locale?: string;
}

export interface GoogleAccountsId {
  initialize: (config: IdConfiguration) => void;
  renderButton: (parent: HTMLElement, options: GoogleButtonOptions) => void;
  disableAutoSelect: () => void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleAccountsId } };
  }
}

const GIS_SRC = "https://accounts.google.com/gsi/client";
const UNAVAILABLE = "Google sign-in could not load. Check your connection, or allow accounts.google.com if a blocker stops it.";

let loading: Promise<GoogleAccountsId> | null = null;
let initializedFor: string | null = null;
let onCredential: ((credential: string) => void) | null = null;

/** The page's language: Google otherwise words its button in the language of the visitor's region. */
export function pageLanguage(): string {
  return document.documentElement.lang || "en";
}

/** The library, loaded on first use; a failed load can be tried again. */
export function loadGoogle(): Promise<GoogleAccountsId> {
  const ready = window.google?.accounts?.id;
  if (ready) return Promise.resolve(ready);
  loading ??= new Promise<GoogleAccountsId>((resolve, reject) => {
    const script = document.createElement("script");
    // A query does not change how the page's security policy matches the library's address.
    script.src = `${GIS_SRC}?${new URLSearchParams({ hl: pageLanguage() }).toString()}`;
    script.async = true;
    script.onload = () => {
      const id = window.google?.accounts?.id;
      if (id) resolve(id);
      else reject(new Error(UNAVAILABLE));
    };
    script.onerror = () => {
      script.remove();
      reject(new Error(UNAVAILABLE));
    };
    document.head.append(script);
  }).catch((error: unknown) => {
    loading = null;
    throw error;
  });
  return loading;
}

/**
 * Initializes the library once for the client id (Google remembers only the last call, so a second button must not
 * call it again) and routes the ID token it returns to `handle`.
 */
export function routeCredentials(id: GoogleAccountsId, clientId: string, handle: (credential: string) => void): void {
  onCredential = handle;
  if (initializedFor === clientId) return;
  initializedFor = clientId;
  id.initialize({
    client_id: clientId,
    callback: (response) => {
      onCredential?.(response.credential);
    },
    auto_select: false,
    cancel_on_tap_outside: true,
    context: "signin",
    ux_mode: "popup",
    itp_support: true,
  });
}

/** After signing out, Google must not sign the same account in again by itself. */
export function forgetGoogleChoice(): void {
  window.google?.accounts?.id?.disableAutoSelect();
}
