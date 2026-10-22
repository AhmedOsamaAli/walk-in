import { useEffect, useState } from "react";
import { messageOf } from "../api/client";
import type { Concept, Design } from "../api/types";
import { letter, list, priceLabel } from "../lib/format";
import { hasLaunchPlan } from "../lib/launch";
import { loadDesign, shotsOf } from "../state/designs";
import { ErrorBoundary } from "./ErrorBoundary";
import { ExperiencePlanView } from "./ExperiencePlan";
import { HoursText } from "./Hours";
import { LaunchPlanView } from "./LaunchPlan";
import { Plate } from "./Plate";
import { PriceAnchors } from "./Price";
import { RenderFrame } from "./RenderFrame";

interface SheetProps {
  runId: string;
  index: number;
  concept: Concept;
}

/** "60 m² (646 ft²), a light-prep kitchen, no outdoor space": only what the owner said. */
function unitText(unit: Design["unit"]): string | null {
  if (!unit) return null;
  const parts = [
    unit.size !== "unknown" ? unit.size : null,
    unit.kitchen !== "unknown" ? unit.kitchen : null,
    unit.outdoor_space === "yes" ? "outdoor space" : unit.outdoor_space === "none" ? "no outdoor space" : null,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

function Drafting({ concept, index }: Omit<SheetProps, "runId">) {
  return (
    <>
      <div className="d-main">
        <p className="d-eyebrow mono">Design sheet · Concept {letter(index)} · drafting</p>
        <h2 className="d-title" id="design-title">
          {concept.name}
        </h2>
        <div className="sk sk-line" />
        <div className="sk sk-line" />
        <div className="sk sk-block" />
      </div>
      <aside className="d-side">
        <div className="d-side-inner">
          <div className="sk sk-card tall" />
          <div className="sk sk-card" />
          <div className="sk sk-card" />
        </div>
      </aside>
    </>
  );
}

function SheetError({ concept, message }: { concept: Concept; message: string }) {
  return (
    <div className="d-main">
      <p className="d-eyebrow mono">Design sheet</p>
      <h2 className="d-title" id="design-title">
        {concept.name}
      </h2>
      <p className="d-p">{message}</p>
    </div>
  );
}

function Sheet({ runId, index, concept, design }: SheetProps & { design: Design }) {
  const interior = design.interior ?? {};
  const priced = priceLabel(design.price_level ?? concept.price_level);
  const priceBasis = design.price_basis ?? concept.price_basis;
  const rows: [string, string | null | undefined, string | null | undefined][] = [
    ["Mood", interior.mood, null],
    ["Decor & materials", list(interior.materials).join(", "), null],
    ["Lighting", interior.lighting, null],
    ["Layout", interior.layout, null],
    ["Seating", interior.seating, null],
    ["Price", priced || (priceBasis ? "Not listed" : null), priceBasis],
    ["Hours", design.hours, design.hours_basis],
    ["Unit", unitText(design.unit), null],
    ["Capacity", design.capacity, design.capacity_basis],
  ];
  const spec = rows.filter((row): row is [string, string, string | null | undefined] => Boolean(row[1]));
  const offer = list(design.offer);
  const artists = list(design.music?.artists);
  const direction = design.music?.direction;
  const partners = (design.partners ?? []).filter((partner) => partner.name);
  const name = design.name ?? concept.name;
  const inspired = list(concept.inspired_by);
  const madeBy = design.mode === "agent" ? (design.model ?? "agent") : "evidence rules";
  const shots = design.renders?.enabled ? shotsOf(design) : [];
  const volunteer = (design.renders?.model ?? "").includes("AI Horde");

  return (
    <>
      <div className="d-main">
        <p className="d-eyebrow mono">
          Design sheet · Concept {letter(index)} · {concept.genre} · {madeBy}
        </p>
        <h2 className="d-title" id="design-title">
          {name}
        </h2>
        <p className="d-tagline">{design.tagline ?? concept.one_liner}</p>
        {design.concept_statement ? <p className="d-statement serif">{design.concept_statement}</p> : null}
        <h3 className="d-h">Interior</h3>
        <dl className="spec">
          {spec.map(([key, value, basis]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>
                {key === "Hours" ? <HoursText hours={value} /> : value}
                {basis ? <small className="spec-basis">{basis}</small> : null}
                {key === "Price" ? <PriceAnchors anchors={design.price_anchors ?? concept.price_anchors} /> : null}
              </dd>
            </div>
          ))}
        </dl>
        {offer.length ? (
          <>
            <h3 className="d-h">The offer</h3>
            <ol className="offer">
              {offer.map((item, k) => (
                <li key={k}>{item}</li>
              ))}
            </ol>
          </>
        ) : null}
        {design.experience ? (
          <>
            <h3 className="d-h">Experience</h3>
            {direction ? <p className="d-p">{direction}</p> : null}
            <ExperiencePlanView plan={design.experience} />
          </>
        ) : artists.length || direction ? (
          <>
            <h3 className="d-h">Sound</h3>
            {direction ? <p className="d-p">{direction}</p> : null}
            <div className="tags d-sound">
              {artists.map((artist) => (
                <span className="tag blue" key={artist}>
                  {artist}
                </span>
              ))}
            </div>
          </>
        ) : null}
        {partners.length ? (
          <>
            <h3 className="d-h">Partners</h3>
            <ul className="partners">
              {partners.map((partner, k) => (
                <li key={k}>
                  <b>{partner.name}</b>
                  <span>{partner.why}</span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {hasLaunchPlan(design.launch) ? (
          <>
            <h3 className="d-h">Launch</h3>
            <p className="d-p launch-lede">
              Who to reach, where and when, and only what the evidence lets an ad say. Paste the settings into each
              platform.
            </p>
            <LaunchPlanView plan={design.launch} />
          </>
        ) : null}
        {concept.risk ? (
          <>
            <h3 className="d-h">Risk</h3>
            <p className="d-p">{concept.risk}</p>
          </>
        ) : null}
      </div>
      <aside className="d-side">
        <div className="d-side-inner">
          {shots.length ? (
            <div className="renders">
              {shots.map((shot) => (
                <RenderFrame key={shot.kind} runId={runId} index={index} shot={shot} name={name} volunteer={volunteer} />
              ))}
            </div>
          ) : null}
          <Plate dna={design.dna ?? {}} />
          <p className="d-source mono">
            Design DNA read from the locals&apos; favorite {concept.genre} places
            {inspired.length ? `: ${inspired.join(", ")}` : ""}.
          </p>
        </div>
      </aside>
    </>
  );
}

/** The sheet's text loads first; renders follow, one request per shot. */
export function DesignContent({ runId, index, concept }: SheetProps) {
  const [loaded, setLoaded] = useState<{ design: Design } | { error: string } | null>(null);

  useEffect(() => {
    let live = true;
    loadDesign(runId, index).then(
      (design) => {
        if (live) setLoaded({ design });
      },
      (error: unknown) => {
        if (live) setLoaded({ error: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [runId, index]);

  return (
    <div className="design-body" aria-busy={loaded === null}>
      {loaded === null ? (
        <Drafting concept={concept} index={index} />
      ) : "error" in loaded ? (
        <SheetError concept={concept} message={loaded.error} />
      ) : (
        <ErrorBoundary
          fallback={<SheetError concept={concept} message="This sheet could not be drawn. Run the site again, or open another concept." />}
        >
          <Sheet runId={runId} index={index} concept={concept} design={loaded.design} />
        </ErrorBoundary>
      )}
    </div>
  );
}
