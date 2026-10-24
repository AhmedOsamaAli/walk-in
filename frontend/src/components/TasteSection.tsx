import { Fragment, useState } from "react";
import type { TasteEntity, TastePayload } from "../api/types";
import { safeUrl } from "../lib/format";
import { initials } from "../lib/initials";
import { toSection } from "../lib/journey";
import { SectionHead } from "./SectionHead";

/** Where Walk-in puts a list to work: the launch plan's ad settings (launch.py) or the experience plan (experience.py). */
interface Use {
  where: string;
  what: string;
}

const USES = {
  artists: [
    { where: "Spotify Ads", what: "the launch plan targets their fans" },
    { where: "Soundtrack", what: "what the room plays" },
  ],
  podcasts: [
    { where: "Spotify Ads", what: "the launch plan targets their listeners" },
    { where: "Talks", what: "podcasts to host or play, at bars, venues and cafés" },
  ],
  screen: [{ where: "Screenings", what: "for bars and venues only" }],
  brands: [{ where: "Who to reach", what: "listed in each launch plan's audience" }],
} satisfies Record<string, Use[]>;

function NameItem({ entity }: { entity: TasteEntity }) {
  const [broken, setBroken] = useState(false);
  const image = safeUrl(entity.image);
  const meta = entity.year ? String(entity.year) : entity.since ? `since ${entity.since}` : null;
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
        <span className="ph" aria-hidden="true">
          {initials(entity.name)}
        </span>
      )}
      <span className="nm">
        {entity.name}
        {meta ? <small className="mono">{meta}</small> : null}
      </span>
    </li>
  );
}

interface NamesProps {
  title: string;
  uses: Use[];
  entities: TasteEntity[];
  empty: string;
}

/** One list, labelled with where Walk-in uses it. */
function Names({ title, uses, entities, empty }: NamesProps) {
  const shown = entities.slice(0, 8);
  return (
    <div className="taste-list">
      <h3 className="label mono">{title}</h3>
      <ul className="taste-uses" aria-label={`Where Walk-in uses the ${title.toLowerCase()}`}>
        {uses.map((use) => (
          <li key={use.where}>
            <b>{use.where}:</b> {use.what}
          </li>
        ))}
      </ul>
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
  no: string;
  taste: TastePayload;
  cues: string[];
}

/**
 * What people here over-index on, by what Walk-in does with it. Only the distinctive names are shown: the area's plain
 * favorites are everyone's, and nothing uses them.
 */
export function TasteSection({ no, taste, cues }: TasteSectionProps) {
  const artists = taste.distinctive_artists ?? [];
  const podcasts = taste.distinctive_podcasts ?? [];
  const screen = [...(taste.distinctive_movies ?? []).slice(0, 4), ...(taste.distinctive_tv ?? []).slice(0, 4)];
  const brands = taste.distinctive_brands ?? [];
  const words = marqueeWords(brands, artists);
  return (
    <section id="s-taste" className="sec reveal">
      <SectionHead
        no={no}
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
        <Names title="Artists" uses={USES.artists} entities={artists} empty="No artist stands out here." />
        <Names title="Podcasts" uses={USES.podcasts} entities={podcasts} empty="No podcast stands out here." />
      </div>
      {screen.length || brands.length ? (
        <div className="taste-grid">
          <Names title="Films and shows" uses={USES.screen} entities={screen} empty="No film or show stands out here." />
          <Names title="Brands" uses={USES.brands} entities={brands} empty="No brand stands out here." />
        </div>
      ) : null}
      <h3 className="label mono">Passions around here, not storefronts</h3>
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
      {/* The last section: the way back to what to act on. Only the one for this survey shows (styles/journey.css). */}
      <p className="sec-next" data-next-to="designs">
        <b className="sec-next-label mono">Next</b>
        <span>Open a concept's design sheet, then make its launch kit.</span>
        <a className="sec-next-link" href="#s-concepts" onClick={toSection("s-concepts")}>
          Back to the concepts <span aria-hidden="true">↑</span>
        </a>
      </p>
      <p className="sec-next" data-next-to="moves">
        <b className="sec-next-label mono">Next</b>
        <span>Make the first change on the list.</span>
        <a className="sec-next-link" href="#s-improve" onClick={toSection("s-improve")}>
          Back to what to change <span aria-hidden="true">↑</span>
        </a>
      </p>
    </section>
  );
}