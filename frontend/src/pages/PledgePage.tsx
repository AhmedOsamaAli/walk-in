import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { canRetry, commerce, paypalOf, type CampaignProgress, type CampaignView, type PledgeHeld } from "../api/commerce";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CopyButton } from "../components/CopyButton";
import { Link } from "../components/Link";
import { Page, useDocumentTitle, useFocusOnMount } from "../components/Page";
import { PayPalPay, type PayNote } from "../components/PayPalPay";
import { SandboxNotice } from "../components/SandboxNotice";
import { absoluteUrl, campaignStatusText, dateTimeText, inSandbox, moneyText, plainError, timeLeft } from "../lib/commerce";
import { cssVars, cx } from "../lib/css";
import { useNavigate } from "../lib/navigation";
import { BRIEF_URL, pledgeUrl } from "../lib/routes";
import { useNow } from "../lib/useNow";
import { session, useSession } from "../state/session";

type CampaignLoad =
  | { state: "loading" }
  | { state: "shown"; view: CampaignView }
  | { state: "missing" }
  | { state: "failed"; message: string };

/** A campaign by its id, read again when the reader signs in or out (the owner's view differs). */
function useCampaign(id: string, signedIn: string | null) {
  const [load, setLoad] = useState<CampaignLoad>({ state: "loading" });
  const [run, setRun] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    commerce.campaign(id, abort.signal).then(
      (view) => {
        setLoad({ state: "shown", view });
      },
      (error: unknown) => {
        if (abort.signal.aborted) return;
        setLoad(
          error instanceof ApiError && error.status === 404
            ? { state: "missing" }
            : { state: "failed", message: plainError(error, "The campaign could not be loaded.") },
        );
      },
    );
    return () => {
      abort.abort();
    };
  }, [id, signedIn, run]);
  return {
    load,
    reload: () => {
      setRun((count) => count + 1);
    },
    replace: (view: CampaignView) => {
      setLoad({ state: "shown", view });
    },
    progress: (progress: CampaignProgress) => {
      setLoad((previous) => (previous.state === "shown" ? { state: "shown", view: { ...previous.view, progress } } : previous));
    },
  };
}

// ---------- A supporter's pledge, remembered in this browser so its withdraw link is not lost ----------

const PLEDGE_KEY = "walk-in-pledge:";

interface Remembered {
  number: number;
  url: string;
}

function remembered(id: string): Remembered | null {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(PLEDGE_KEY + id) ?? "null");
    if (typeof value === "object" && value !== null && "number" in value && "url" in value) {
      const { number, url } = value;
      if (typeof number === "number" && typeof url === "string" && url.startsWith("/")) return { number, url };
    }
  } catch {
    // Nothing remembered.
  }
  return null;
}

function remember(id: string, pledge: Remembered | null): void {
  try {
    if (pledge) window.localStorage.setItem(PLEDGE_KEY + id, JSON.stringify(pledge));
    else window.localStorage.removeItem(PLEDGE_KEY + id);
  } catch {
    // Private browsing can refuse storage.
  }
}

const CLOSED: Record<CampaignView["status"], string> = {
  open: "Pledges are closed, and the campaign is being settled.",
  collected: "It met its goal, and every pledge was collected.",
  partial: "It met its goal; PayPal is still collecting some of the pledges.",
  expired: "It ended short of its goal, so every hold was released: nobody paid.",
  cancelled: "The owner cancelled it, so every hold was released: nobody paid.",
};

const COUNTS: [string, string][] = [
  ["authorized", "Held"],
  ["captured", "Collected"],
  ["voided", "Released"],
  ["declined", "Declined"],
  ["expired", "Hold ran out"],
  ["failed", "Could not be collected"],
  ["created", "Started, not approved"],
];

function Progress({ view, now }: { view: CampaignView; now: number }) {
  const { progress } = view;
  const left = timeLeft(view.closed_at ?? view.deadline, now);
  const share = progress.goal > 0 ? Math.min(1, progress.supporters / progress.goal) : 0;
  const dots = progress.goal <= 40 ? progress.goal : 0;
  return (
    <div className={cx("pledge-progress", progress.funded && "funded")}>
      <p className="pp-count">
        <b>{progress.supporters}</b>
        <span>
          of {progress.goal} supporters
          <small className="mono">{progress.funded ? "Goal met" : `${progress.remaining} more needed`}</small>
        </span>
      </p>
      <div
        className="pp-bar"
        role="progressbar"
        aria-label="Supporters so far"
        aria-valuemin={0}
        aria-valuemax={progress.goal}
        aria-valuenow={Math.min(progress.supporters, progress.goal)}
        aria-valuetext={`${progress.supporters} of ${progress.goal} supporters`}
        style={cssVars({ "--p": share })}
      >
        <i />
      </div>
      {dots ? (
        <p className="pp-dots" aria-hidden="true">
          {Array.from({ length: dots }, (_, index) => (
            <i key={index} className={index < progress.supporters ? "on" : undefined} />
          ))}
        </p>
      ) : null}
      <dl className="pp-facts">
        <div>
          <dt className="mono">{left.closed ? "Closed" : "Time left"}</dt>
          <dd>{left.closed ? campaignStatusText(view.status, view.accepting) : left.text.replace(/ left$/, "")}</dd>
        </div>
        <div>
          <dt className="mono">Deadline</dt>
          <dd>{dateTimeText(view.deadline)}</dd>
        </div>
        <div>
          <dt className="mono">Pledged so far</dt>
          <dd>{moneyText(progress.total, view.currency)}</dd>
        </div>
      </dl>
    </div>
  );
}

function WithdrawLink({ url }: { url: string }) {
  const box = useRef<HTMLElement>(null);
  const full = absoluteUrl(url);
  return (
    <p className="held-link">
      <code ref={box}>{full}</code>
      <CopyButton text={full} what="your withdraw link" target={box} />
    </p>
  );
}

function Held({ view, number, url }: { view: CampaignView; number: number; url: string }) {
  return (
    <div className="pledge-held" role="status">
      <p className="held-kicker mono">Pledge held by PayPal</p>
      <p className="held-number">
        You&apos;re supporter <b>#{number}</b>
      </p>
      <p className="held-text">
        PayPal is holding {moneyText(view.amount, view.currency)}. It is collected only if {view.goal} people pledge by{" "}
        {dateTimeText(view.deadline)}; if not, PayPal releases it and you pay nothing.
      </p>
      <p className="held-link-label mono">Your withdraw link</p>
      <WithdrawLink url={url} />
      <p className="held-note">Keep it: it is the only way to withdraw your pledge before the deadline.</p>
    </div>
  );
}

interface PledgeActionProps {
  view: CampaignView;
  onHeld: (held: PledgeHeld) => void;
  onClosed: () => void;
}

function PledgeAction({ view, onHeld, onClosed }: PledgeActionProps) {
  const { phase, config } = useSession();
  const paypal = paypalOf(config);
  const [note, setNote] = useState<PayNote>(null);
  const [confirming, setConfirming] = useState(false);
  const amount = moneyText(view.amount, view.currency);

  if (!view.accepting) {
    return (
      <div className="pledge-closed">
        <p className="pledge-closed-title">This campaign is closed</p>
        <p>{CLOSED[view.status]}</p>
      </div>
    );
  }

  async function createOrder(): Promise<string> {
    try {
      return (await commerce.pledge(view.id)).order_id;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setNote({ tone: "error", text: plainError(error, "This campaign no longer takes pledges.") });
        onClosed();
      } else setNote({ tone: "error", text: plainError(error, "The pledge could not be started. Try again.") });
      throw error;
    }
  }

  async function authorize(orderId: string): Promise<"done" | "retry"> {
    setConfirming(true);
    setNote({ tone: "info", text: "Placing the hold with PayPal…" });
    try {
      const held = await commerce.authorizePledge(view.id, orderId);
      setNote(null);
      onHeld(held);
      return "done";
    } catch (error) {
      setConfirming(false);
      if (canRetry(error)) {
        setNote({ tone: "error", text: plainError(error, "PayPal declined that payment method. Choose another way to pay.") });
        return "retry";
      }
      setNote({ tone: "error", text: plainError(error, "PayPal could not place the hold, so nothing is held. Try again.") });
      return "done";
    }
  }

  let body;
  if (phase === "loading") body = <div className="sk sk-pay" aria-hidden="true" />;
  else if (!config) body = <p className="pay-note" data-tone="error">PayPal&apos;s settings could not be loaded. Reload the page to try again.</p>;
  else if (!paypal?.enabled) {
    body = <p className="kit-offer-off">Pledges are off on this server: PayPal isn&apos;t configured here.</p>;
  } else {
    body = (
      <div hidden={confirming}>
        <PayPalPay
          paypal={paypal}
          intent="authorize"
          label={`Pledge ${amount} to ${view.name} with PayPal`}
          createOrder={createOrder}
          approve={authorize}
          onNote={setNote}
        />
      </div>
    );
  }

  return (
    <div className="pledge-action">
      <p className="pledge-amount">
        <b>{amount}</b>
        <span>Pledge once. PayPal only holds it until the deadline.</span>
      </p>
      {inSandbox(paypal) ? <SandboxNotice judges /> : null}
      {body}
      <p className="pay-note" data-tone={note?.tone} role="status" aria-live="polite">
        {note?.text ?? ""}
      </p>
    </div>
  );
}

function Withdraw({ view, token, onDone }: { view: CampaignView; token: string; onDone: (progress: CampaignProgress) => void }) {
  const navigate = useNavigate();
  const { config } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function withdraw() {
    setBusy(true);
    setError(null);
    try {
      const { progress } = await commerce.withdraw(view.id, token);
      onDone(progress);
    } catch (failure) {
      setError(plainError(failure, "The pledge could not be withdrawn. Try again in a moment."));
      setBusy(false);
    }
  }
  return (
    <div className="pledge-withdraw" aria-labelledby="withdraw-title">
      <h2 className="withdraw-title" id="withdraw-title">
        Withdraw your pledge?
      </h2>
      <p>
        PayPal releases the hold on your {moneyText(view.amount, view.currency)}, so nothing is charged.
        {view.accepting ? " You can pledge again while the campaign is open." : ""}
      </p>
      {inSandbox(paypalOf(config)) ? <SandboxNotice /> : null}
      <div className="withdraw-actions">
        <button type="button" className="ink-button danger" disabled={busy} onClick={() => void withdraw()}>
          {busy ? "Withdrawing…" : "Withdraw my pledge"}
        </button>
        <button
          type="button"
          className="ghost mono"
          disabled={busy}
          onClick={() => {
            navigate(pledgeUrl(view.id), { replace: true });
          }}
        >
          Keep my pledge
        </button>
      </div>
      <p className="pay-note" data-tone="error" role="status">
        {error ?? ""}
      </p>
    </div>
  );
}

function OwnerPanel({ view, onView }: { view: CampaignView; onView: (view: CampaignView) => void }) {
  const { config } = useSession();
  const [asking, setAsking] = useState<"close" | "cancel" | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const box = useRef<HTMLElement>(null);
  const shareUrl = absoluteUrl(pledgeUrl(view.id));
  const counts = COUNTS.map(([key, label]) => [label, view.owner?.counts[key] ?? 0] as const).filter(([, count]) => count > 0);
  const { progress } = view;

  async function act(action: "close" | "cancel") {
    setBusy(true);
    setNote(action === "close" ? "Closing and settling…" : "Cancelling and releasing every hold…");
    try {
      const next = action === "close" ? await commerce.closeCampaign(view.id) : await commerce.cancelCampaign(view.id);
      onView(next);
      setNote(action === "close" ? "Closed. The settlement report is below." : "Cancelled. Every hold is being released.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) void session.refresh();
      setNote(plainError(error, "That did not go through. Try again in a moment."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="owner-panel" aria-labelledby="owner-title">
      <h2 className="owner-title" id="owner-title">
        Your campaign
      </h2>
      <p className="mono owner-label">Share this page</p>
      <p className="held-link">
        <code ref={box}>{shareUrl}</code>
        <CopyButton text={shareUrl} what="the campaign's link" target={box} />
      </p>
      {counts.length ? (
        <dl className="owner-counts">
          {counts.map(([label, count]) => (
            <div key={label}>
              <dt className="mono">{label}</dt>
              <dd>{count}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="owner-empty">No pledges yet. Share the page, and print the poster from your kit.</p>
      )}
      {view.accepting ? (
        <div className="owner-actions">
          <button
            type="button"
            className="ink-button"
            disabled={busy}
            onClick={() => {
              setAsking("close");
            }}
          >
            Close now
          </button>
          <button
            type="button"
            className="ghost mono danger"
            disabled={busy}
            onClick={() => {
              setAsking("cancel");
            }}
          >
            Cancel the campaign
          </button>
        </div>
      ) : null}
      {view.owner?.report?.length ? (
        <div className="owner-report">
          <p className="mono owner-label">Settlement report</p>
          <ul>
            {view.owner.report.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="owner-status" role="status">
        {note ?? ""}
      </p>
      <ConfirmDialog
        open={asking !== null}
        title={asking === "cancel" ? "Cancel the campaign?" : "Close the campaign now?"}
        confirm={asking === "cancel" ? "Cancel the campaign" : "Close now"}
        cancel="Keep it open"
        danger
        onConfirm={() => {
          const action = asking;
          setAsking(null);
          if (action) void act(action);
        }}
        onCancel={() => {
          setAsking(null);
        }}
      >
        <p>
          {asking === "cancel"
            ? "Every hold is released and nobody pays. This can't be undone."
            : progress.funded
              ? `The goal is met, so every held pledge is collected now: ${progress.supporters} supporters, ${moneyText(progress.total, view.currency)}. This can't be undone.`
              : `The goal isn't met (${progress.supporters} of ${progress.goal}), so every hold is released and nobody pays. This can't be undone.`}
        </p>
        {inSandbox(paypalOf(config)) ? <SandboxNotice /> : null}
      </ConfirmDialog>
    </section>
  );
}

/** The public pledge page, with the owner's controls when the owner reads it. */
export function PledgePage({ id, withdraw }: { id: string; withdraw: string | null }) {
  const { user } = useSession();
  const navigate = useNavigate();
  const { load, reload, replace, progress } = useCampaign(id, user?.id ?? null);
  const titleRef = useFocusOnMount();
  const placeholderRef = useFocusOnMount();
  const [pledge, setPledge] = useState<Remembered | null>(() => remembered(id));
  const [withdrawn, setWithdrawn] = useState(false);
  const now = useNow(30_000);
  const view = load.state === "shown" ? load.view : null;
  useDocumentTitle(view ? view.title : "Founding supporters");

  if (!view) {
    return (
      <Page className="pledge-page">
        <header className="page-head">
          <p className="eyebrow mono">
            <b>Founding</b> supporters
          </p>
          <h1 className="page-title" ref={placeholderRef} tabIndex={-1}>
            {load.state === "missing" ? "This campaign isn't here" : "Founding supporters"}
          </h1>
        </header>
        <section className="pg-sec" aria-busy={load.state === "loading"}>
          {load.state === "loading" ? (
            <>
              <div className="sk sk-line" />
              <div className="sk sk-block" />
            </>
          ) : load.state === "missing" ? (
            <p className="kit-state-lead">
              The link may be mistyped, or the campaign was removed.{" "}
              <Link className="text-link" href={BRIEF_URL}>
                Survey a storefront <span aria-hidden="true">→</span>
              </Link>
            </p>
          ) : (
            <p className="page-alert" role="alert">
              {load.state === "failed" ? load.message : ""}{" "}
              <button type="button" className="text-button" onClick={reload}>
                Try again
              </button>
            </p>
          )}
        </section>
      </Page>
    );
  }

  const asking = withdraw !== null && !withdrawn;
  return (
    <Page className="pledge-page">
      <div className="pledge-layout">
        <div className="pledge-main">
          <header className="pledge-hero">
            <p className="eyebrow mono">
              <b>Founding</b> supporters{view.neighborhood ? ` · ${view.neighborhood}` : ""}
            </p>
            <h1 className="pledge-title" ref={titleRef} tabIndex={-1}>
              {view.title}
            </h1>
            <p className="pledge-business">
              <span className="pledge-name">{view.name}</span>
              <span className="pledge-genre mono">{view.concept.genre}</span>
            </p>
            <p className="pledge-pitch">{view.pitch}</p>
          </header>
          {view.perks.length ? (
            <section className="pledge-sec" aria-labelledby="pledge-perks">
              <h2 className="pledge-h" id="pledge-perks">
                What founding supporters get
              </h2>
              <ol className="offer pledge-perks">
                {view.perks.map((perk) => (
                  <li key={perk}>{perk}</li>
                ))}
              </ol>
            </section>
          ) : null}
          <section className="pledge-sec" aria-labelledby="pledge-how">
            <h2 className="pledge-h" id="pledge-how">
              How it works
            </h2>
            <ol className="pledge-steps" aria-hidden="true">
              <li>
                <b>Pledge</b>
                <span>{moneyText(view.amount, view.currency)}, once</span>
              </li>
              <li>
                <b>PayPal holds it</b>
                <span>Nothing is charged yet</span>
              </li>
              <li>
                <b>{view.goal} by the deadline?</b>
                <span>Collected if so, released if not</span>
              </li>
            </ol>
            <p className="pledge-how-text">{view.how_it_works}</p>
          </section>
          <section className="pledge-sec" aria-labelledby="pledge-about">
            <h2 className="pledge-h" id="pledge-about">
              The business
            </h2>
            <p className="pledge-summary">{view.concept.summary}</p>
            <Link className="text-link" href={view.survey_url}>
              See the evidence for this block <span aria-hidden="true">→</span>
            </Link>
          </section>
        </div>
        <aside className="pledge-side" aria-label="Pledge">
          <div className="pledge-card">
            <Progress view={view} now={now} />
            {withdrawn ? (
              <p className="pledge-done" role="status">
                Your pledge is withdrawn: PayPal has released the hold, so nothing is charged.
              </p>
            ) : null}
            {asking ? (
              <Withdraw
                view={view}
                token={withdraw}
                onDone={(next) => {
                  progress(next);
                  remember(id, null);
                  setPledge(null);
                  setWithdrawn(true);
                  navigate(pledgeUrl(id), { replace: true });
                }}
              />
            ) : pledge && view.accepting ? (
              <Held view={view} number={pledge.number} url={pledge.url} />
            ) : (
              <PledgeAction
                view={view}
                onClosed={reload}
                onHeld={(held) => {
                  const kept = { number: held.supporter_number, url: held.withdraw_url };
                  remember(id, kept);
                  setPledge(kept);
                  progress(held.progress);
                }}
              />
            )}
          </div>
          {view.is_owner ? <OwnerPanel view={view} onView={replace} /> : null}
        </aside>
      </div>
    </Page>
  );
}
