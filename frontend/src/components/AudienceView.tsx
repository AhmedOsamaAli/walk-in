import { Fragment } from "react";
import type { Audience } from "../api/types";
import { adText, barSpan, bandsText, compareRows, leanWord, namedBands, namesOnce, peopleNote, type InsideAudience } from "../lib/audience";
import { cssVars, cx } from "../lib/css";
import { naturalList } from "../lib/format";

/** One band's track: its middle is everyone, and the bar runs right for more of that age, left for fewer. */
function Track({ lean }: { lean: number }) {
  const span = barSpan(lean);
  return (
    <span className="aud-track" aria-hidden="true">
      <i style={cssVars({ "--from": `${span.left}%`, "--size": `${span.width}%` })} />
    </span>
  );
}

/** Six age bands, each a short track whose middle is everyone: a bar to the right means more of that age than everyone,
 * to the left fewer. The bands of the age group the server names are marked. */
export function AudienceBars({ audience, compact = false }: { audience: Audience; compact?: boolean }) {
  const named = namedBands(audience);
  return (
    <div className={cx("aud-bars", compact && "compact")} role="img" aria-label={`Ages, against everyone. ${bandsText(audience)}.`}>
      {audience.bands.map(({ band, lean }) => (
        <div className="aud-band" key={band} data-lean={leanWord(lean)} data-top={named.has(band) ? "" : undefined}>
          <Track lean={lean} />
          <span className="aud-band-name mono" aria-hidden="true">
            {band}
          </span>
        </div>
      ))}
    </div>
  );
}

/** The loved places' six bands over those of the places of this kind already inside the area, on one scale and one set
 * of band names, so the contrast shows: who you'd win against who is served now. */
function AudienceCompare({ audience, inside, area }: { audience: Audience; inside: InsideAudience; area: string }) {
  const rows = compareRows(audience, inside, area);
  const said = rows.map((row) => `${row.name}: ${bandsText(row)}`).join(". ");
  return (
    <div className="aud-bars aud-compare" role="img" aria-label={`Ages, against everyone. ${said}.`}>
      {rows.map((row) => (
        <Fragment key={row.key}>
          <span className="aud-row-name mono" aria-hidden="true">
            {row.name}
          </span>
          {row.bands.map(({ band, lean }) => (
            // Only the loved row marks its age group: the people to win.
            <span
              className="aud-band"
              key={band}
              data-row={row.key}
              data-lean={leanWord(lean)}
              data-top={row.key === "loved" && row.named.has(band) ? "" : undefined}
            >
              <Track lean={lean} />
            </span>
          ))}
        </Fragment>
      ))}
      {audience.bands.map(({ band }) => (
        <span className="aud-band-name mono" key={band} aria-hidden="true" data-top={rows[0]?.named.has(band) ? "" : undefined}>
          {band}
        </span>
      ))}
    </div>
  );
}

/** The design sheet's audience: who the loved places draw (or the category everywhere, when too few of them have data),
 * against who the places of this kind already inside the area draw when the server read them, the positioning tip when
 * the two part ways, the ad setting that follows, and what it is read from. Its title is the caller's: see
 * audienceTitle. */
export function WhoYoudWin({ audience, area }: { audience: Audience; area: string }) {
  const ad = adText(audience);
  return (
    <div className="aud">
      <p className="aud-line">{audience.line}</p>
      {audience.tip ? <p className="aud-tip">{audience.tip}</p> : null}
      {audience.inside ? <AudienceCompare audience={audience} inside={audience.inside} area={area} /> : <AudienceBars audience={audience} />}
      <p className="aud-key">The middle of each bar is everyone: a bar to the right means more people of that age, to the left fewer.</p>
      {audience.gender || ad ? (
        <dl className="aud-facts">
          {audience.gender ? (
            <div>
              <dt className="mono">Gender</dt>
              <dd>Leans {audience.gender}</dd>
            </div>
          ) : null}
          {ad ? (
            <div>
              <dt className="mono">Ads</dt>
              <dd>{ad}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      <p className="aud-basis">
        {audience.places.length && !audience.general ? `Read from ${naturalList(namesOnce(audience.places))}. ` : ""}
        {audience.inside?.places.length ? `Already inside: ${naturalList(namesOnce(audience.inside.places))}. ` : ""}
        {audience.basis}
      </p>
    </div>
  );
}

/** The launch plan's reminder of who its settings aim at: the bars, small, and the line unless the sheet shows it above. */
export function PeopleStrip({ people, above }: { people: Audience; above: boolean }) {
  return (
    <div className="aud-strip">
      <AudienceBars audience={people} compact />
      <p>{peopleNote(people, above)}</p>
    </div>
  );
}
