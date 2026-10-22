import { useEffect, useState } from "react";
import { PLACES_URL } from "../lib/routes";
import { session, useSession } from "../state/session";
import { Link } from "./Link";
import { SignInOptions } from "./SignIn";

const KEY = "walk-in-keep-surveys";
/** "Not now" quiets the offer for two weeks in this browser. */
const QUIET_MS = 14 * 86_400_000;

function quieted(): boolean {
  try {
    const at = Number(window.localStorage.getItem(KEY));
    return Number.isFinite(at) && at > 0 && Date.now() - at < QUIET_MS;
  } catch {
    return false;
  }
}

function quiet(): void {
  try {
    window.localStorage.setItem(KEY, String(Date.now()));
  } catch {
    // Private browsing can refuse storage; the offer then returns on the next survey.
  }
}

/**
 * Below a survey that just finished in this browser, for someone signed out: an optional offer to keep their surveys.
 * It never stands in the way of a survey, says so once the reader signs in, and keeps quiet for two weeks after "Not
 * now". Surveys this browser ran join the account at sign-in (the device cookie), so the offer is only made for those.
 */
export function KeepSurveys() {
  const { phase, config, user } = useSession();
  const [dismissed, setDismissed] = useState(quieted);
  const [saved, setSaved] = useState(false);
  const canSignIn = Boolean(config?.google_client_id ?? config?.dev_login);
  const offered = phase === "ready" && !user && canSignIn && !dismissed;

  useEffect(() => {
    if (!offered) return;
    return session.subscribe(() => {
      if (session.get().user) setSaved(true);
    });
  }, [offered]);

  if (saved && user) {
    return (
      <aside className="sec keep saved" aria-label="Your surveys are kept">
        <p className="keep-done" role="status">
          Signed in. This survey, and the others this browser ran, are saved to your account.{" "}
          <Link className="text-link" href={PLACES_URL}>
            Open My places <span aria-hidden="true">→</span>
          </Link>
        </p>
      </aside>
    );
  }
  if (!offered) return null;
  return (
    <aside className="sec keep" aria-labelledby="keep-title">
      <div className="keep-card">
        <div className="keep-text">
          <p className="keep-kicker mono">Optional</p>
          <h2 className="keep-title" id="keep-title">
            Keep your surveys
          </h2>
          <p className="keep-lead">
            Sign in and the surveys you run are saved to My places, on any device, together with the ones this browser has
            already run. Surveys work just the same without it.
          </p>
        </div>
        <div className="keep-sign">
          <SignInOptions />
          <button
            type="button"
            className="text-button keep-later"
            onClick={() => {
              quiet();
              setDismissed(true);
            }}
          >
            Not now
          </button>
        </div>
      </div>
    </aside>
  );
}
