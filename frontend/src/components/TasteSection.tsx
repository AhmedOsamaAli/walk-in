import { Fragment, useState } from "react";
import type { TasteEntity, TastePayload } from "../api/types";
import { safeUrl } from "../lib/format";
import { SectionHead } from "./SectionHead";

function NameItem({ entity }: { entity: TasteEntity }) {
  const [broken, setBroken] = useState(false);
  const image = safeUrl(entity.image);
  return (
    <li>
      {image && !broken ? (
        <img
          src={image}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => {
            setBroken(true);
          }}
        />
      ) : (
        <span className="ph" />
      )}
      <span className="nm">{entity.name}</span>
    </li>
  );
}

function Names({ title, entities, empty }: { title: string; entities: TasteEntity[]; empty: string }) {
  const shown = entities.slice(0, 8);
  return (
    <div>
      <h3 className="label mono">{title}</h3>
      <ol className="names">
        {shown.length ? (
          shown.map((entity, k) => <NameItem key={`${entity.name ?? ""}-${k}`} entity={entity} />)
        ) : (
          <li className="muted">
            <span className="nm">{empty}</span>
          </li>
        )}
      </ol>
    </div>
  );
}

/** Enough names to fill the marquee, which plays the run twice to loop seamlessly. */
function marqueeWords(brands: TasteEntity[], artists: TasteEntity[]): string[] {
  let words = [...brands.slice(0, 6), ...artists.slice(0, 6)]
    .map((entity) => entity.name)
    .filter((name): name is string => Boolean(name));
  if (!words.length) return [];
  while (words.length < 10) words = words.concat(words);
  return words;
}

interface TasteSectionProps {
  taste: TastePayload;
  cues: string[];
}

export function TasteSection({ taste, cues }: TasteSectionProps) {
  const brands = taste.distinctive_brands?.length ? taste.distinctive_brands : (taste.brands ?? []);
  const artists = taste.distinctive_artists?.length ? taste.distinctive_artists : (taste.artists ?? []);
  const words = marqueeWords(brands, artists);
  return (
    <section id="s-taste" className="sec reveal">
      <SectionHead
        no="05"
        title="The wider taste"
        note="What this neighborhood over-indexes on compared with same-size areas around it."
      />
      {words.length ? (
        <div className="marquee" aria-hidden="true">
          <div className="marquee-track">
            {[...words, ...words].map((word, k) => (
              <Fragment key={k}>
                <span>{word}</span>
                <i />
              </Fragment>
            ))}
          </div>
        </div>
      ) : null}
      <div className="taste-grid">
        <Names title="Brands" entities={brands} empty="No brand data." />
        <Names title="Artists" entities={artists} empty="No artist data." />
      </div>
      <h3 className="label mono">Local passions, not storefronts</h3>
      <div className="tags">
        {cues.length ? (
          cues.map((cue) => (
            <span className="tag blue" key={cue}>
              {cue}
            </span>
          ))
        ) : (
          <span className="muted">None detected.</span>
        )}
      </div>
    </section>
  );
}
