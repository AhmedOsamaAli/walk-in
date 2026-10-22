import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import { commerce, paypalOf, type KitView } from "../api/commerce";
import type { Kit } from "../api/kit";
import { BrandMark } from "../components/BrandMark";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CopyButton } from "../components/CopyButton";
import { CampaignForm } from "../components/kit/CampaignForm";
import { CopyChecks, CopyDeck } from "../components/kit/CopyDeck";
import { DossierBody, dossierContents, dossierGist } from "../components/kit/DossierView";
import { PosterSection } from "../components/kit/PosterSection";
import { TrackedLinks, useLanding } from "../components/kit/TrackedLinks";
import { Link } from "../components/Link";
import { Page, PageHead, useDocumentTitle, useFocusOnMount } from "../components/Page";
import { SandboxNotice } from "../components/SandboxNotice";
import { SectionHead } from "../components/SectionHead";
import { absoluteUrl, dateText, inSandbox, plainError, trackedUrl } from "../lib/commerce";
import { letter } from "../lib/format";
import { BRIEF_URL, dossierUrl, PLACES_URL } from "../lib/routes";
import { useNow } from "../lib/useNow";
import { useKit } from "../state/kit";
import { session, useSession } from "../state/session";

const BUILD_STEPS = [
  "The design sheet, if the concept had none yet",
  "Ad copy for each channel, every line checked against the evidence",
  "The window poster, drawn from the walk",
  "Tracked links for every channel",
  "The dossier",
];

function since(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (!Number.isFinite(seconds)) return "";
  return seconds < 90 ? `${seconds} s ago` : `${Math.round(seconds / 60)} min ago`;
}

function Building({ view, stalled, onCheck }: { view: KitView; stalled: string | null; onCheck: () => void }) {
  const now = useNow(1000);
  const elapsed = (now - Date.parse(view.created_at)) / 1000;
  const progress = Number.isFinite(elapsed) ? Math.min(0.78, Math.max(0.05, elapsed / 75)) : 0.2;
  return (
    <section className="pg-sec kit-state" data-state="building" aria-labelledby="kit-building">
      <div className="kit-walk" aria-hidden="true">
        <BrandMark state="walking" progress={progress} />
      </div>
      <div className="kit-state-text">
        <h2 className="kit-state-title" id="kit-building">
          Building your kit
        </h2>
        <p className="kit-state-lead">
          About a minute. This page fills in by itself as soon as the kit is ready; you can leave and come back from My
          places.
        </p>
        <ol className="kit-steps">
          {BUILD_STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="kit-state-meta mono" role="status">
          {stalled ? "" : `Started ${since(view.created_at, now)} · checking every 2 seconds`}
        </p>
        {stalled ? (
          <p className="page-alert" role="alert">
            {stalled}{" "}
            <button type="button" className="text-button" onClick={onCheck}>
              Check again
            </button>
          </p>
        ) : null}
      </div>
    </section>
  );
}

function Failed({ view, onRetried }: { view: KitView; onRetried: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function retry() {
    setBusy(true);
    setError(null);
    try {
      await commerce.retryKit(view.token);
      onRetried();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) void session.refresh();
      setError(plainError(failure, "The kit could not be started again. Try again in a moment."));
      setBusy(false);
    }
  }
  return (
    <section className="pg-sec kit-state" data-state="failed" aria-labelledby="kit-failed">
      <p className="kit-state-mark mono">Not built</p>
      <div className="kit-state-text">
        <h2 className="kit-state-title" id="kit-failed">
          The kit could not be built
        </h2>
        <p className="kit-state-lead">{view.error ?? "Something went wrong while it was being built."}</p>
        {view.is_owner ? (
          <button type="button" className="ink-button" disabled={busy} onClick={() => void retry()}>
            {busy ? "Starting again…" : "Build it again"}
          </button>
        ) : (
          <p className="kit-state-lead">The owner can build it again from this page.</p>
        )}
        <p className="pay-note" data-tone="error" role="status">
          {error ?? ""}
        </p>
      </div>
    </section>
  );
}

function Refunded({ view }: { view: KitView }) {
  return (
    <section className="pg-sec kit-state" data-state="refunded" aria-labelledby="kit-refunded">
      <p className="kit-state-mark mono">Refunded</p>
      <div className="kit-state-text">
        <h2 className="kit-state-title" id="kit-refunded">
          This kit was refunded
        </h2>
        <p className="kit-state-lead">
          PayPal returned the payment and the kit was closed. The survey and its free design sheet are still there.
        </p>
        <Link className="ink-button" href={view.survey_url}>
          Open the survey <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  );
}

function OwnerBar({ view, onRefunded }: { view: KitView; onRefunded: () => void }) {
  const { config } = useSession();
  const now = useNow(60_000);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const refundable = view.refundable_until !== null && Date.parse(view.refundable_until) > now && view.status !== "building";

  async function refund() {
    setBusy(true);
    setNote("Refunding through PayPal…");
    try {
      await commerce.refundKit(view.token);
      setNote("Refunded. PayPal returns the payment to the account that paid.");
      onRefunded();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) void session.refresh();
      setNote(plainError(error, "The refund did not go through. Try again in a moment."));
      setBusy(false);
    }
  }

  return (
    <div className="owner-bar">
      <p className="owner-bar-note">
        <span className="mono">Your kit</span>
        {refundable && view.refundable_until ? ` Refundable until ${dateText(view.refundable_until)}.` : " Saved to My places."}
      </p>
      <div className="owner-bar-actions">
        {view.campaign_url ? (
          <Link className="ink-button" href={view.campaign_url}>
            Open your campaign <span aria-hidden="true">→</span>
          </Link>
        ) : view.status === "ready" ? (
          <a className="ink-button" href="#kit-campaign">
            Start a founding-supporter campaign
          </a>
        ) : null}
        {refundable ? (
          <button
            type="button"
            className="ghost mono"
            disabled={busy}
            onClick={() => {
              setAsking(true);
            }}
          >
            Refund
          </button>
        ) : null}
      </div>
      <p className="owner-bar-status" role="status">
        {note ?? ""}
      </p>
      <ConfirmDialog
        open={asking}
        title="Refund this kit?"
        confirm="Refund the kit"
        cancel="Keep the kit"
        danger
        onConfirm={() => {
          setAsking(false);
          void refund();
        }}
        onCancel={() => {
          setAsking(false);
        }}
      >
        <p>
          PayPal returns your payment to the account that paid, and the kit closes: its copy, poster, links and dossier stop
          opening.
        </p>
        {inSandbox(paypalOf(config)) ? <SandboxNotice /> : null}
      </ConfirmDialog>
    </div>
  );
}

function CampaignLink({ url, owner, name }: { url: string; owner: boolean; name: string }) {
  const box = useRef<HTMLElement>(null);
  const full = absoluteUrl(url);
  return (
    <div className="campaign-live">
      <p className="campaign-live-lead">
        {owner ? "Your founding-supporter campaign is live." : `${name} is gathering founding supporters.`}
      </p>
      <p className="campaign-live-url">
        <code ref={box}>{full}</code>
        <CopyButton text={full} what="the campaign's link" target={box} />
      </p>
      <Link className="ink-button" href={url}>
        {owner ? "Open the pledge page" : "See the campaign"} <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}

function Ready({ view, kit, onChanged }: { view: KitView; kit: Kit; onChanged: () => void }) {
  const { config } = useSession();
  const { website, invalid, landing, setWebsite } = useLanding(view.token, view.campaign_url, view.survey_url);
  const posterLink = kit.links.find((link) => link.key === "poster");
  const posterUrl = posterLink ? trackedUrl(landing.url, posterLink.query) : landing.url;
  const contents = dossierContents(kit.dossier);
  const cover = kit.dossier.cover;
  const paypal = paypalOf(config);

  return (
    <>
      {view.is_owner ? <OwnerBar view={view} onRefunded={onChanged} /> : null}

      <section className="pg-sec" aria-labelledby="kit-copy">
        <SectionHead
          id="kit-copy"
          no="01"
          title="Ad copy"
          note="One piece per channel of the launch plan. Every line was checked against the evidence: no number it does not give, no other business's name, no superlative."
        />
        <CopyDeck kit={kit} />
        <CopyChecks kit={kit} />
      </section>

      <section className="pg-sec" aria-labelledby="kit-poster">
        <SectionHead id="kit-poster" no="02" title="The window poster" note="Print it for the window: the QR code is the poster's own tracked link." />
        <PosterSection poster={kit.poster} link={posterUrl} landing={landing} />
      </section>

      <section className="pg-sec" aria-labelledby="kit-links">
        <SectionHead
          id="kit-links"
          no="03"
          title="Tracked links"
          note="One link per channel, tagged so your analytics can tell which channel brought each visit."
        />
        <TrackedLinks links={kit.links} landing={landing} website={website} invalid={invalid} onWebsite={setWebsite} />
      </section>

      <section className="pg-sec" aria-labelledby="kit-dossier">
        <SectionHead
          id="kit-dossier"
          no="04"
          title="The dossier"
          note="The case for this business, to take to a landlord or a bank. Every section says what it rests on."
        />
        <div className="dz-preview">
          <div className="dz-preview-head">
            <Link className="ink-button" href={dossierUrl(view.token)}>
              Open the dossier <span aria-hidden="true">→</span>
            </Link>
            <p className="dz-preview-note">
              A printable document{cover ? ` prepared ${dateText(cover.prepared_date, { timeZone: "UTC" })}` : ""}: open it, then
              “Save as PDF”.
            </p>
          </div>
          <ol className="dz-toc">
            {contents.map(({ key, no, title }) => (
              <li key={key}>
                <details className="dz-fold">
                  <summary>
                    <span className="dz-no mono">{no}</span>
                    <span className="dz-fold-text">
                      <h3 className="dz-fold-title">{title}</h3>
                      <span className="dz-gist">{dossierGist(kit.dossier, key)}</span>
                    </span>
                    <span className="dz-fold-mark" aria-hidden="true" />
                  </summary>
                  <div className="dz-fold-body dz-doc-body">
                    <DossierBody dossier={kit.dossier} part={key} level={3} />
                  </div>
                </details>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {view.is_owner || view.campaign_url ? (
        <section className="pg-sec" id="kit-campaign" aria-labelledby="kit-campaign-title">
          <SectionHead
            id="kit-campaign-title"
            no="05"
            title="Founding supporters"
            note="Neighbors pledge a fixed amount through PayPal, which only holds it: it is collected if enough of them pledge by the deadline, and released if not."
          />
          {view.campaign_url ? (
            <CampaignLink url={view.campaign_url} owner={view.is_owner} name={kit.concept.name} />
          ) : !paypal ? (
            <div className="sk sk-row" />
          ) : !paypal.enabled ? (
            <p className="kit-offer-off">Pledges need PayPal, which isn&apos;t configured on this server.</p>
          ) : (
            <CampaignForm token={view.token} name={kit.concept.name} currency={paypal.currency} sandbox={inSandbox(paypal)} />
          )}
        </section>
      ) : null}
    </>
  );
}

/** A launch kit by its link: followed while it is built, then its copy, poster, links, dossier and campaign. */
export function KitPage({ token }: { token: string }) {
  const { user } = useSession();
  const { load, restart } = useKit(token, user?.id ?? null);
  const titleRef = useFocusOnMount();
  const view = load.state === "shown" ? load.view : null;
  const kit = view?.status === "ready" ? view.kit : null;
  const name = kit?.concept.name ?? view?.name ?? null;
  useDocumentTitle(name ? `${name} launch kit` : "Launch kit");

  const cover = kit?.dossier.cover;
  const fields = kit
    ? [
        { label: "Site", lines: [cover?.site_label ?? "—"] },
        {
          label: "Walk",
          lines: [`${kit.poster.minutes}-min walk`, ...(cover?.area_km2 != null ? [`${cover.area_km2} km²`] : [])],
        },
        { label: "Built", lines: [dateText(kit.built_at)] },
        { label: "Copy written by", lines: [kit.mode === "agent" ? (kit.model ?? "The agent") : "Evidence rules"] },
      ]
    : undefined;

  const eyebrow = view
    ? `Launch kit · Concept ${letter(view.index)}${kit ? ` · ${kit.concept.genre}` : ""}`
    : "Launch kit";

  return (
    <Page className="kit-page">
      <PageHead
        eyebrow={eyebrow}
        title={load.state === "missing" ? "This kit isn't here" : (name ?? "Launch kit")}
        titleRef={titleRef}
        standfirst={kit ? (cover?.tagline ?? kit.poster.tagline ?? undefined) : undefined}
        fields={fields}
        actions={
          view ? (
            <Link className="ghost mono" href={view.survey_url}>
              Open the survey
            </Link>
          ) : undefined
        }
      />
      {load.state === "loading" ? (
        <section className="pg-sec" aria-busy="true">
          <div className="sk sk-line" />
          <div className="sk sk-block" />
        </section>
      ) : null}
      {load.state === "missing" ? (
        <section className="pg-sec kit-state" data-state="missing">
          <div className="kit-state-text">
            <p className="kit-state-lead">The link may be mistyped, or the kit was removed. Kits you bought are in My places.</p>
            <p className="kit-state-links">
              <Link className="ink-button" href={PLACES_URL}>
                My places
              </Link>
              <Link className="ghost mono" href={BRIEF_URL}>
                Survey a storefront
              </Link>
            </p>
          </div>
        </section>
      ) : null}
      {load.state === "failed" ? (
        <section className="pg-sec">
          <p className="page-alert" role="alert">
            {load.message}{" "}
            <button type="button" className="text-button" onClick={restart}>
              Try again
            </button>
          </p>
        </section>
      ) : null}
      {view?.status === "building" ? <Building view={view} stalled={load.state === "shown" ? load.stalled : null} onCheck={restart} /> : null}
      {view?.status === "failed" ? <Failed view={view} onRetried={restart} /> : null}
      {view?.status === "refunded" ? <Refunded view={view} /> : null}
      {view && kit ? <Ready view={view} kit={kit} onChanged={restart} /> : null}
      {view?.status === "ready" && !kit ? (
        <section className="pg-sec">
          <p className="page-alert" role="alert">
            The kit is ready but came without its contents. Reload the page to try again.
          </p>
        </section>
      ) : null}
    </Page>
  );
}
