import type { KitView } from "../api/commerce";
import type { Kit } from "../api/kit";
import { DOSSIER_TITLES, DossierBody, dossierContents, dossierGist } from "../components/kit/DossierView";
import { WalkDrawing } from "../components/kit/WalkDrawing";
import { Link } from "../components/Link";
import { useDocumentTitle, useFocusOnMount } from "../components/Page";
import { dateText } from "../lib/commerce";
import { fmtLat, fmtLon } from "../lib/format";
import { kitUrl, PLACES_URL } from "../lib/routes";
import { useKit } from "../state/kit";
import { useSession } from "../state/session";

function Toolbar({ token, name }: { token: string; name: string | null }) {
  return (
    <div className="dz-toolbar no-print">
      <Link className="ghost mono" href={kitUrl(token)}>
        <span aria-hidden="true">←</span> Back to the kit
      </Link>
      <p className="dz-toolbar-title mono">{name ? `${name} · Decision dossier` : "Decision dossier"}</p>
      <button
        type="button"
        className="ink-button"
        onClick={() => {
          window.print();
        }}
      >
        Save as PDF
      </button>
    </div>
  );
}

function Document({ kit, titleRef }: { kit: Kit; titleRef: (node: HTMLElement | null) => void }) {
  const { dossier } = kit;
  const cover = dossier.cover;
  const contents = dossierContents(dossier);
  const walk = cover ? [`${cover.walk_minutes}-minute walk`, cover.walk_source, cover.area_km2 != null ? `${cover.area_km2} km²` : null, cover.reach_m ? `reaching ${cover.reach_m} m` : null] : [];
  return (
    <article className="dz-doc" aria-labelledby="dz-title">
      <header className="dz-cover">
        <p className="dz-kicker mono">Decision dossier{cover ? ` · ${cover.genre}` : ""}</p>
        <h1 className="dz-name" id="dz-title" ref={titleRef} tabIndex={-1}>
          {cover?.concept ?? kit.concept.name}
        </h1>
        {cover?.tagline ? <p className="dz-tagline">{cover.tagline}</p> : null}
        <div className="dz-cover-grid">
          {cover ? <WalkDrawing ring={cover.ring} site={[cover.lat, cover.lon]} minutes={cover.walk_minutes} /> : null}
          {cover ? (
            <dl className="dz-facts">
              <div>
                <dt className="mono">Site</dt>
                <dd>
                  {cover.site_label}
                  <small className="mono">
                    {fmtLat(cover.lat)} · {fmtLon(cover.lon)}
                  </small>
                </dd>
              </div>
              <div>
                <dt className="mono">Catchment</dt>
                <dd>{walk.filter(Boolean).join(", ")}</dd>
              </div>
              {cover.neighborhoods.length ? (
                <div>
                  <dt className="mono">Neighborhoods</dt>
                  <dd>{cover.neighborhoods.join(", ")}</dd>
                </div>
              ) : null}
              <div>
                <dt className="mono">Evidence</dt>
                <dd>Surveyed {dateText(cover.evidence_date, { timeZone: "UTC" })}</dd>
              </div>
              <div>
                <dt className="mono">Prepared</dt>
                <dd>{dateText(cover.prepared_date, { timeZone: "UTC" })}, with Walk-in</dd>
              </div>
            </dl>
          ) : null}
        </div>
        <nav className="dz-contents" aria-label="Contents">
          <p className="dz-kicker mono">Contents</p>
          <ol>
            {contents.map(({ key, no, title }) => (
              <li key={key}>
                <a href={`#dz-${key}`}>
                  <span className="mono">{no}</span>
                  <span>{title}</span>
                  <small>{dossierGist(dossier, key)}</small>
                </a>
              </li>
            ))}
          </ol>
        </nav>
        {cover?.sources.length ? (
          <div className="dz-sources">
            <p className="dz-kicker mono">Sources</p>
            <ul>
              {cover.sources.map((source) => (
                <li key={source.name}>
                  <b>{source.name}</b>: {source.used_for}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {cover?.basis ? (
          <p className="dz-basis">
            <span className="mono">Basis</span> {cover.basis}
          </p>
        ) : null}
      </header>
      {contents.map(({ key, no }) => (
        <section className="dz-sec" id={`dz-${key}`} key={key} aria-labelledby={`dz-${key}-title`} data-section={key}>
          <header className="dz-head">
            <span className="dz-no mono">{no}</span>
            <h2 className="dz-title" id={`dz-${key}-title`}>
              {DOSSIER_TITLES[key]}
            </h2>
          </header>
          <div className="dz-doc-body">
            <DossierBody dossier={dossier} part={key} level={2} />
          </div>
        </section>
      ))}
      <footer className="dz-end mono">
        {kit.concept.name} · Decision dossier · Prepared with Walk-in
        {cover ? ` on ${dateText(cover.prepared_date, { timeZone: "UTC" })} from evidence surveyed ${dateText(cover.evidence_date, { timeZone: "UTC" })}` : ""}.
        Taste data by Qloo.
      </footer>
    </article>
  );
}

function Waiting({ view, message, titleRef }: { view: KitView | null; message: string; titleRef: (node: HTMLElement | null) => void }) {
  return (
    <div className="dz-wait" role="status">
      <h1 className="dz-kicker mono" ref={titleRef} tabIndex={-1}>
        Decision dossier
      </h1>
      <p className="dz-wait-text">{message}</p>
      {view ? (
        <Link className="ghost mono" href={kitUrl(view.token)}>
          Open the kit
        </Link>
      ) : (
        <Link className="ghost mono" href={PLACES_URL}>
          My places
        </Link>
      )}
    </div>
  );
}

/** The dossier as a document: read on screen, printed or saved as a PDF with the page's print styles. */
export function DossierPage({ token }: { token: string }) {
  const { user } = useSession();
  const { load } = useKit(token, user?.id ?? null);
  const titleRef = useFocusOnMount();
  const waitRef = useFocusOnMount();
  const view = load.state === "shown" ? load.view : null;
  const kit = view?.status === "ready" ? view.kit : null;
  useDocumentTitle(kit ? `${kit.concept.name} dossier` : "Dossier");

  let body;
  if (kit) body = <Document kit={kit} titleRef={titleRef} />;
  else if (load.state === "loading") body = <div className="dz-wait sk" aria-busy="true" />;
  else {
    const message =
      load.state === "missing"
        ? "This dossier's link isn't valid, or its kit is no longer available."
        : load.state === "failed"
          ? load.message
          : view?.status === "building"
            ? "The dossier is still being written. This page shows it as soon as the kit is ready."
            : view?.status === "refunded"
              ? "This kit was refunded, so its dossier is closed."
              : (view?.error ?? "The kit could not be built, so there is no dossier yet.");
    body = <Waiting view={view} message={message} titleRef={waitRef} />;
  }

  return (
    <main className="page dossier-page" id="main">
      <Toolbar token={token} name={kit?.concept.name ?? view?.name ?? null} />
      {body}
    </main>
  );
}
