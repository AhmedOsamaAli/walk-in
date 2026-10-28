import { useId, useState } from "react";
import type { ConceptTheme, ThemeCard, ThemeDraws } from "../api/types";
import { safeUrl } from "../lib/format";
import { initials } from "../lib/initials";
import { DOMAIN_LABELS, DRAWS_BASIS, drawsText } from "../lib/wildTheme";

/**
 * A title the theme is built on: Qloo's picture in a square that holds its place while it loads, or the name's
 * initials when there is none or it fails; then the name and what it is. The name is written under the picture, so the
 * picture has no alt text of its own: a screen reader would read the name twice.
 */
function Title({ card }: { card: ThemeCard }) {
  const [broken, setBroken] = useState(false);
  const image = safeUrl(card.image);
  return (
    <li className="theme-title">
      <span className="theme-pic">
        {image && !broken ? (
          <img
            src={image}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => {
              setBroken(true);
            }}
          />
        ) : (
          <span className="ph mono" aria-hidden="true">
            {initials(card.name)}
          </span>
        )}
      </span>
      <span className="theme-name">{card.name}</span>
      <span className="theme-domain mono">
        <span className="sr-only">, </span>
        {DOMAIN_LABELS[card.domain]}
      </span>
    </li>
  );
}

function BuiltOn({ cards }: { cards: ThemeCard[] }) {
  const labelId = useId();
  return (
    <div className="theme-part">
      <p className="theme-label mono" id={labelId}>
        Built on what people here over-index on
      </p>
      <ul className="theme-titles" aria-labelledby={labelId}>
        {cards.map((card) => (
          <Title key={`${card.domain}-${card.id || card.name}`} card={card} />
        ))}
      </ul>
    </div>
  );
}

function Draws({ draws }: { draws: ThemeDraws }) {
  const line = drawsText(draws);
  if (!line) return null;
  return (
    <p className="theme-draws">
      <b className="theme-label mono">Draws</b>
      {line}
      <small>{draws.basis || DRAWS_BASIS}</small>
    </p>
  );
}

interface WildThemeProps {
  theme: ConceptTheme;
  /** How many of the titles to show: a few on the poster, all of them on the design sheet. */
  titles?: number;
}

/**
 * What a themed wild card is built around: the titles, artists and brands people here over-index on, what happens
 * there, and who those titles' fans lean to. Each part that has nothing to show is left out.
 */
export function WildTheme({ theme, titles }: WildThemeProps) {
  const cards = theme.built_on.slice(0, titles);
  return (
    <>
      {cards.length ? <BuiltOn cards={cards} /> : null}
      {theme.program.length ? (
        <div className="theme-part theme-program">
          <b className="theme-label mono">What happens there</b>
          <ul>
            {theme.program.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {theme.draws ? <Draws draws={theme.draws} /> : null}
    </>
  );
}
