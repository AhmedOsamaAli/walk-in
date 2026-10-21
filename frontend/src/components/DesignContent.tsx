import { useEffect, useState } from "react";
import { messageOf } from "../api/client";
import type { Concept, Design } from "../api/types";
import { letter, list, price } from "../lib/format";
import { loadDesign, shotsOf } from "../state/designs";
import { Plate } from "./Plate";
import { RenderFrame } from "./RenderFrame";

interface SheetProps {
  runId: string;
  index: number;
  concept: Concept;
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

function Sheet({ runId, index, concept, design }: SheetProps & { design: Design }) {
  const interior = design.interior ?? {};
  const rows: [string, string | null | undefined][] = [
    ["Mood", interior.mood],
    ["Decor & materials", list(interior.materials).join(", ")],
    ["Lighting", interior.lighting],
    ["Layout", interior.layout],
    ["Seating", interior.seating],
    ["Price", price(design.price_level ?? concept.price_level)],
    ["Hours", design.hours],
  ];
  const spec = rows.filter((row): row is [string, string] => Boolean(row[1]));
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
          {spec.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
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
        {artists.length || direction ? (
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
        <div className="d-main">
          <p className="d-eyebrow mono">Design sheet</p>
          <h2 className="d-title" id="design-title">
            {concept.name}
          </h2>
          <p className="d-p">{loaded.error}</p>
        </div>
      ) : (
        <Sheet runId={runId} index={index} concept={concept} design={loaded.design} />
      )}
    </div>
  );
}
