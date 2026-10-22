import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { canRetry, commerce, conflictUrl, paypalOf } from "../api/commerce";
import type { LaunchPlan } from "../api/types";
import { inSandbox, moneyText, plainError } from "../lib/commerce";
import { naturalList } from "../lib/format";
import { CHANNEL_NAMES, kitChannels } from "../lib/kit";
import { useNavigate } from "../lib/navigation";
import { session, useSession } from "../state/session";
import { Link } from "./Link";
import { PayPalPay, type PayNote } from "./PayPalPay";
import { SandboxNotice } from "./SandboxNotice";
import { SignInOptions } from "./SignIn";

interface KitOfferProps {
  runId: string;
  index: number;
  /** The business's name on the sheet. */
  name: string;
  plan: LaunchPlan | null | undefined;
}

/** What the kit holds, said exactly: the copy follows the channels of this concept's launch plan. */
function Contents({ plan }: { plan: LaunchPlan | null | undefined }) {
  const ads = kitChannels(plan).filter((key) => key !== "poster");
  return (
    <ol className="kit-contents">
      <li>
        <b>Ad copy</b>
        {ads.length ? ` for ${naturalList(ads.map((key) => CHANNEL_NAMES[key]))} and the poster` : " for the poster"}, each line
        checked against the evidence, ready to paste.
      </li>
      <li>
        <b>A window poster</b> drawn from the walk&apos;s real outline, with a QR code, ready to print.
      </li>
      <li>
        <b>Tracked links</b> for every channel, so you see which one brings people in.
      </li>
      <li>
        <b>A dossier</b> of up to twelve sections to take to a landlord or a bank: the case, the competition, the offer and
        prices, the first 90 days and the questions to ask before you sign.
      </li>
      <li>
        <b>Founding supporters</b>: start a pledge campaign from the kit. Neighbors pledge, and nobody pays unless enough of
        them do.
      </li>
    </ol>
  );
}

/** The owned kit's address, once known for this account and concept. */
interface Owned {
  key: string;
  url: string | null;
}

/** The kit for one concept: what is inside, its price, and PayPal once the reader is signed in and does not own it yet. */
export function KitOffer({ runId, index, name, plan }: KitOfferProps) {
  const { phase, config, user } = useSession();
  const navigate = useNavigate();
  const key = user ? `${user.id}:${runId}:${index}` : null;
  const [owned, setOwned] = useState<Owned | null>(null);
  const [note, setNote] = useState<PayNote>(null);
  const [confirming, setConfirming] = useState(false);
  /** An approved order the server could not confirm yet: capturing again is safe, it returns the same kit. */
  const [unconfirmed, setUnconfirmed] = useState<string | null>(null);

  useEffect(() => {
    if (!key) return;
    const abort = new AbortController();
    commerce.ownedKit(runId, index, abort.signal).then(
      ({ kit_url }) => {
        setOwned({ key, url: kit_url });
      },
      (error: unknown) => {
        if (abort.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) void session.refresh();
        // Unknown ownership still offers the kit: the server refuses to sell it twice.
        setOwned({ key, url: null });
      },
    );
    return () => {
      abort.abort();
    };
  }, [key, runId, index]);

  async function createOrder(): Promise<string> {
    try {
      return (await commerce.checkout(runId, index)).order_id;
    } catch (error) {
      const url = conflictUrl(error);
      if (url && key) {
        setOwned({ key, url });
        setNote({ tone: "info", text: "You already own this kit." });
      } else {
        if (error instanceof ApiError && error.status === 401) void session.refresh();
        setNote({ tone: "error", text: plainError(error, "PayPal's order could not be created. Try again.") });
      }
      throw error;
    }
  }

  async function capture(orderId: string): Promise<"done" | "retry"> {
    setConfirming(true);
    setNote({ tone: "info", text: "Confirming your payment with PayPal…" });
    try {
      const { kit_url } = await commerce.capture(orderId);
      setUnconfirmed(null);
      setNote({ tone: "info", text: "Paid. Opening your kit…" });
      navigate(kit_url);
      return "done";
    } catch (error) {
      setConfirming(false);
      if (canRetry(error)) {
        setNote({ tone: "error", text: plainError(error, "PayPal declined that payment method. Choose another way to pay.") });
        return "retry";
      }
      const url = conflictUrl(error);
      if (url && key) {
        setOwned({ key, url });
        setNote({ tone: "info", text: "You already own this kit." });
        return "done";
      }
      setUnconfirmed(orderId);
      setNote({
        tone: "error",
        text: plainError(error, "The payment could not be confirmed yet.") + " Confirming again is safe: you are never charged twice.",
      });
      return "done";
    }
  }

  const paypal = paypalOf(config);
  const price = paypal ? moneyText(paypal.kit_price, paypal.currency) : null;
  const known = owned !== null && owned.key === key;

  let body;
  if (phase === "loading") body = <div className="sk sk-pay" aria-hidden="true" />;
  else if (!config) body = <SignInOptions />;
  else if (!paypal?.enabled) {
    body = (
      <p className="kit-offer-off">
        Payments are off on this server: PayPal isn&apos;t configured here, so the kit can&apos;t be bought on this copy of
        Walk-in.
      </p>
    );
  } else if (!user) {
    body = <SignInOptions why="Sign in first: the kit is saved to your account, so you can open it on any device." />;
  } else if (!known) body = <div className="sk sk-pay" aria-hidden="true" />;
  else if (owned.url) {
    body = (
      <div className="kit-owned">
        <p>You own this kit.</p>
        <Link className="ink-button" href={owned.url}>
          Open your kit <span aria-hidden="true">→</span>
        </Link>
      </div>
    );
  } else if (unconfirmed) {
    body = (
      <button
        type="button"
        className="ink-button"
        disabled={confirming}
        onClick={() => {
          void capture(unconfirmed);
        }}
      >
        Confirm the payment again
      </button>
    );
  } else {
    body = (
      <div className="kit-pay" hidden={confirming}>
        <PayPalPay
          paypal={paypal}
          intent="capture"
          label={`Pay ${price ?? ""} for the ${name} launch kit with PayPal`}
          createOrder={createOrder}
          approve={capture}
          onNote={setNote}
        />
      </div>
    );
  }

  return (
    <section className="kit-offer" aria-labelledby={`kit-offer-${index}`}>
      <div className="kit-offer-head">
        <p className="kit-offer-eyebrow mono">Launch kit · {name}</p>
        <h4 className="kit-offer-title" id={`kit-offer-${index}`}>
          Everything to open with, written from this evidence
        </h4>
        {price ? (
          <p className="kit-offer-price">
            <b>{price}</b>
            <span className="mono">once</span>
          </p>
        ) : null}
      </div>
      <Contents plan={plan} />
      {paypal?.enabled !== false && inSandbox(paypal) ? <SandboxNotice judges /> : null}
      <div className="kit-offer-body">{body}</div>
      <p className="pay-note" data-tone={note?.tone} role="status" aria-live="polite">
        {note?.text ?? ""}
      </p>
      <p className="kit-offer-fine mono">Saved to My places · Refund it yourself for 14 days</p>
    </section>
  );
}
