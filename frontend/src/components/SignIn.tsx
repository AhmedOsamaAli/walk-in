import { use, useEffect, useRef, useState } from "react";
import { messageOf } from "../api/client";
import { loadGoogle, pageLanguage, routeCredentials } from "../lib/google";
import { PRIVACY_URL } from "../lib/routes";
import { useEngine } from "../state/engine";
import { session, useSession } from "../state/session";
import { ThemeContext } from "../state/theme";
import { Link } from "./Link";

/** Google's own button, drawn for the theme on screen; its ID token signs the user in. */
function GoogleButton({ clientId }: { clientId: string }) {
  const theme = use(ThemeContext);
  const box = useRef<HTMLDivElement>(null);
  const [failure, setFailure] = useState<{ attempt: number; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    const element = box.current;
    loadGoogle().then(
      (id) => {
        if (!live || !element) return;
        routeCredentials(id, clientId, (credential) => {
          void session.signInWithGoogle(credential);
        });
        element.replaceChildren();
        id.renderButton(element, {
          type: "standard",
          theme: theme === "dark" ? "filled_black" : "outline",
          size: "large",
          text: "continue_with",
          shape: "pill",
          logo_alignment: "left",
          width: Math.round(Math.max(200, Math.min(400, element.clientWidth || 280))),
          locale: pageLanguage(),
        });
      },
      (error: unknown) => {
        if (live) setFailure({ attempt, message: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [clientId, theme, attempt]);

  const failed = failure?.attempt === attempt ? failure.message : null;
  return (
    <div className="gsi">
      <div ref={box} className="gsi-button" hidden={failed !== null} />
      {failed ? (
        <p className="signin-error" role="alert">
          {failed}{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setAttempt((count) => count + 1);
            }}
          >
            Try again
          </button>
        </p>
      ) : null}
    </div>
  );
}

/** Development only: any email signs in, so the app can be tried without a Google client id. */
function DevSignIn({ busy }: { busy: boolean }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  return (
    <form
      className="dev-signin"
      onSubmit={(event) => {
        event.preventDefault();
        const address = email.trim();
        if (!address) return;
        const typed = name.trim();
        void session.signInDev(address, typed !== "" ? typed : (address.split("@")[0] ?? address));
      }}
    >
      <p className="dev-tag mono">Development sign-in</p>
      <label className="dev-field">
        <span className="mono">Email</span>
        <input
          className="field-input"
          type="email"
          required
          autoComplete="email"
          placeholder="tester@example.com"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
      </label>
      <label className="dev-field">
        <span className="mono">Name</span>
        <input
          className="field-input"
          type="text"
          autoComplete="name"
          placeholder="Tester"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </label>
      <button className="ink-button" type="submit" disabled={busy}>
        Sign in
      </button>
    </form>
  );
}

interface SignInOptionsProps {
  /** Why to sign in here, in a sentence. */
  why?: string;
}

/** Every way this server lets someone sign in: Google, a development form, or neither, said plainly. */
export function SignInOptions({ why }: SignInOptionsProps) {
  const { phase, config, busy, error } = useSession();
  const { note } = useEngine();

  if (phase === "loading") {
    return (
      <div className="signin" aria-busy="true">
        <div className="sk sk-pill" />
        {note === "waking" ? <p className="signin-wait">Sign-in will be ready as soon as the survey engine wakes.</p> : null}
      </div>
    );
  }
  if (!config) {
    return (
      <div className="signin">
        <p className="signin-error" role="alert">
          {error ?? "Walk-in's settings could not be loaded."}{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              void session.load();
            }}
          >
            Try again
          </button>
        </p>
      </div>
    );
  }
  const google = config.google_client_id;
  return (
    <div className="signin">
      {why ? <p className="signin-why">{why}</p> : null}
      {google ? <GoogleButton clientId={google} /> : null}
      {!google && config.dev_login ? <DevSignIn busy={busy} /> : null}
      {!google && !config.dev_login ? (
        <p className="signin-off">Sign-in isn&apos;t set up on this server yet, so nothing can be saved to an account here.</p>
      ) : null}
      <p className="signin-status mono" role="status">
        {busy ? "Signing you in…" : ""}
      </p>
      {error ? (
        <p className="signin-error" role="alert">
          {error}
        </p>
      ) : null}
      {google || config.dev_login ? (
        <p className="signin-privacy">
          {google
            ? "Walk-in keeps your Google account id, email, name and picture link, only to list your surveys. "
            : "Walk-in keeps your email and name, only to list your surveys. "}
          <Link className="text-link" href={PRIVACY_URL}>
            How Walk-in handles your data
          </Link>
        </p>
      ) : null}
    </div>
  );
}
