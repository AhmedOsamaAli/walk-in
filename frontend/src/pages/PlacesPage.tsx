import { useCallback, useEffect, useState, type ReactNode } from "react";
import { account, type Places, type PlacesSurvey, type User } from "../api/account";
import { ApiError } from "../api/client";
import { Avatar } from "../components/Avatar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Link } from "../components/Link";
import { Page, PageHead, useDocumentTitle, useFocusOnMount } from "../components/Page";
import { SectionHead } from "../components/SectionHead";
import { SignInOptions } from "../components/SignIn";
import { dateText, plainError, SURVEY_STATUS, surveyOutcome } from "../lib/account";
import { INTENTS } from "../lib/format";
import { forgetGoogleChoice } from "../lib/google";
import { BRIEF_URL, PRIVACY_URL } from "../lib/routes";
import { useEngine } from "../state/engine";
import { session, useSession } from "../state/session";

type PlacesLoad = { state: "loading" } | { state: "shown"; places: Places } | { state: "failed"; message: string };

/** What the survey came to, with the concept or gap it leads with set in the highlighter. */
function Outcome({ survey }: { survey: PlacesSurvey }) {
  if (survey.status === "complete" && survey.headline) {
    return (
      <>
        Leads with <span className="hl">{survey.headline}</span>
      </>
    );
  }
  return <>{surveyOutcome(survey)}</>;
}

function SurveyRow({ survey }: { survey: PlacesSurvey }) {
  return (
    <li>
      <Link className="place-row" href={survey.url}>
        <span className="place-main">
          <span className="place-kicker mono">{INTENTS[survey.intent].label}</span>
          <span className="place-name">{survey.label}</span>
          <span className="place-sub">
            <Outcome survey={survey} />
          </span>
        </span>
        <span className="place-meta mono">
          <span className="state" data-state={survey.status}>
            {SURVEY_STATUS[survey.status]}
          </span>
          <time dateTime={survey.created_at}>{dateText(survey.created_at)}</time>
        </span>
        <span className="place-arrow" aria-hidden="true">
          →
        </span>
      </Link>
    </li>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="places-empty">{children}</div>;
}

/** The account's surveys, newest first. */
function Surveys({ userId }: { userId: string }) {
  const [load, setLoad] = useState<PlacesLoad>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    account.places(abort.signal).then(
      (places) => {
        setLoad({ state: "shown", places });
      },
      (error: unknown) => {
        if (abort.signal.aborted) return;
        // A session that ended elsewhere turns the page into the sign-in prompt.
        if (error instanceof ApiError && error.status === 401) void session.refresh();
        setLoad({ state: "failed", message: plainError(error, "Your surveys could not be loaded.") });
      },
    );
    return () => {
      abort.abort();
    };
  }, [userId, attempt]);

  const surveys = load.state === "shown" ? load.places.surveys : [];
  const note =
    load.state !== "shown"
      ? "Every survey you run while signed in, and the ones this browser ran before you signed in."
      : surveys.length
        ? `${surveys.length} saved, newest first. Each opens just as it ended, and its link can be shared.`
        : "Every survey you run while signed in appears here, and so do the ones this browser ran before you signed in.";

  return (
    <section className="pg-sec" aria-labelledby="places-surveys" aria-busy={load.state === "loading"}>
      <SectionHead id="places-surveys" no="01" title="Surveys" note={note} />
      {load.state === "loading" ? (
        <div className="place-list" aria-hidden="true">
          <div className="sk sk-row" />
          <div className="sk sk-row" />
          <div className="sk sk-row" />
        </div>
      ) : null}
      {load.state === "failed" ? (
        <p className="page-alert" role="alert">
          {load.message}{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setLoad({ state: "loading" });
              setAttempt((count) => count + 1);
            }}
          >
            Try again
          </button>
        </p>
      ) : null}
      {load.state === "shown" ? (
        surveys.length ? (
          <ol className="place-list">
            {surveys.map((survey) => (
              <SurveyRow key={survey.id} survey={survey} />
            ))}
          </ol>
        ) : (
          <Empty>
            <p>No surveys yet.</p>
            <Link className="text-link" href={BRIEF_URL}>
              Survey a storefront <span aria-hidden="true">→</span>
            </Link>
          </Empty>
        )
      ) : null}
    </section>
  );
}

/** How the reader left their account from this page. */
type Left = "deleted" | "signed-out";

/** Said where the account section was, once it is gone; it takes the focus so it isn't lost with the section. */
function Farewell({ left }: { left: Left }) {
  const focus = useCallback((node: HTMLParagraphElement | null) => {
    node?.focus();
  }, []);
  return (
    <p className="page-notice" ref={focus} tabIndex={-1} role="status">
      {left === "deleted"
        ? "Your account and the surveys saved to it are deleted, and their share links no longer work."
        : "You're signed out. Your surveys stay saved to your account."}
    </p>
  );
}

/** Who is signed in, what Walk-in keeps about them, and the ways out: signing out, or deleting the account. */
function AccountSection({ user, onLeft }: { user: User; onLeft: (how: Left) => void }) {
  const { busy, error } = useSession();
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    setDeleting(true);
    const done = await session.deleteAccount();
    setDeleting(false);
    if (done) {
      forgetGoogleChoice();
      onLeft("deleted");
    }
  }

  return (
    <section className="pg-sec" aria-labelledby="places-account">
      <SectionHead id="places-account" no="02" title="Your account" note="What Walk-in keeps about you, and how to remove it." />
      <div className="account-card">
        <div className="account-id">
          <Avatar user={user} className="avatar-large" />
          <p>
            <b>{user.name || user.email}</b>
            {user.name ? <span>{user.email}</span> : null}
          </p>
        </div>
        <p className="account-keeps">
          Walk-in keeps your account id, email, name and picture link, only to show you&apos;re signed in and to list your
          surveys here. Nothing about you is sent to Qloo or the AI providers.{" "}
          <Link className="text-link" href={PRIVACY_URL}>
            How Walk-in handles your data
          </Link>
        </p>
        <div className="account-actions">
          <button
            type="button"
            className="ghost mono"
            disabled={busy}
            onClick={() => {
              void session.signOut().then((done) => {
                if (!done) return;
                forgetGoogleChoice();
                onLeft("signed-out");
              });
            }}
          >
            Sign out
          </button>
          <button
            type="button"
            className="ghost mono danger"
            disabled={busy}
            onClick={() => {
              session.clearError();
              setAsking(true);
            }}
          >
            Delete my account
          </button>
        </div>
        <p className="account-status" role="status">
          {deleting ? "Deleting your account…" : ""}
        </p>
        {error ? (
          <p className="signin-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
      <ConfirmDialog
        open={asking}
        title="Delete your account?"
        confirm="Delete my account"
        cancel="Keep my account"
        danger
        onConfirm={() => {
          setAsking(false);
          void remove();
        }}
        onCancel={() => {
          setAsking(false);
        }}
      >
        <p>Deletes your account and the surveys saved to it; their share links stop working.</p>
        <p>This can&apos;t be undone.</p>
      </ConfirmDialog>
    </section>
  );
}

/** My places: the signed-in user's surveys and account, or the ways to sign in. */
export function PlacesPage() {
  const { phase, user } = useSession();
  const { note } = useEngine();
  const titleRef = useFocusOnMount();
  const [left, setLeft] = useState<Left | null>(null);
  const [shownUser, setShownUser] = useState(user?.id ?? null);
  // Signing in again starts afresh: the note about leaving belongs to the account that left.
  if ((user?.id ?? null) !== shownUser) {
    setShownUser(user?.id ?? null);
    if (user) setLeft(null);
  }
  useDocumentTitle("My places");

  return (
    <Page className="places-page">
      <PageHead
        eyebrow="Account · My places"
        title="My places"
        titleRef={titleRef}
        standfirst={
          user
            ? `Signed in as ${user.email}. Your surveys, saved to your account and open on any device.`
            : "Your surveys, saved to your account and open on any device."
        }
      />
      {user ? (
        <>
          <Surveys key={user.id} userId={user.id} />
          <AccountSection user={user} onLeft={setLeft} />
        </>
      ) : phase === "loading" ? (
        <section className="pg-sec" aria-busy="true">
          {note === "waking" ? <p className="places-wait">Your places will show as soon as the survey engine wakes.</p> : null}
          <div className="sk sk-row" />
        </section>
      ) : (
        <section className="pg-sec signin-prompt" aria-labelledby="places-signin">
          {left ? <Farewell left={left} /> : null}
          <div className="prompt-card">
            <h2 className="prompt-title" id="places-signin">
              Sign in to see your places
            </h2>
            <p className="prompt-text">
              Surveys you run while signed in are saved to your account, and so are the ones this browser ran before you
              signed in. Running a survey never needs an account.
            </p>
            <SignInOptions />
          </div>
        </section>
      )}
    </Page>
  );
}
