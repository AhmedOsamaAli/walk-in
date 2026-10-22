import type { FavoritePlace, GapRow, PlaceCard } from "../api/types";
import { cssVars, cx } from "../lib/css";
import { gapWhy, priceLabel, standingText } from "../lib/format";
import { CountUp } from "./CountUp";
import { PlaceLink, PriceAnchors, PriceLadder } from "./Price";

const MAX_PIPS = 24;

function Competitor({ place }: { place: PlaceCard }) {
  const known = (place.known_for ?? []).slice(0, 2).join(", ");
  const complaints = (place.complaints ?? []).slice(0, 2).join(", ");
  const meta = [
    place.rating ? `★ ${place.rating.toFixed(1)}` : "",
    place.price_level ? "$".repeat(place.price_level) : "",
    standingText(place.standing),
    known ? `known for ${known}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li>
      <span className="n">
        <PlaceLink name={place.name ?? ""} url={place.url} kind={place.link} />
      </span>
      {meta ? <span className="s">{meta}</span> : null}
      {complaints ? (
        <span className="s">
          <span className="hl">{complaints}</span>
        </span>
      ) : null}
    </li>
  );
}

function Favorite({ place }: { place: FavoritePlace }) {
  const where = place.within_walk
    ? "inside the walk"
    : place.distance_m != null
      ? `${(place.distance_m / 1000).toFixed(1)} km away`
      : "";
  const detail = [place.rating ? `★ ${place.rating.toFixed(1)}` : "", place.price_level ? "$".repeat(place.price_level) : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <li>
      <span className="n">
        <PlaceLink name={place.name ?? ""} url={place.url} kind={place.link} />
      </span>
      {detail ? <span className="s">{detail}</span> : null}
      <span className="km">{where}</span>
    </li>
  );
}

function Pips({ gap }: { gap: GapRow }) {
  const shown = Math.min(gap.nearby_count, MAX_PIPS);
  if (!shown) return <span className="mono muted">none</span>;
  return (
    <>
      {Array.from({ length: shown }, (_, k) => (
        <i key={k} />
      ))}
      {gap.nearby_count > MAX_PIPS || gap.nearby_capped ? <i className="more">+</i> : null}
    </>
  );
}

function Dots({ gap }: { gap: GapRow }) {
  if (gap.favorites_kind !== "local") return <span className="dots-note">Same as the city&apos;s famous spots</span>;
  return (
    <>
      {Array.from({ length: gap.favorites_total }, (_, k) => (
        <i key={k} className={k < gap.favorites_far ? "on" : undefined} />
      ))}
    </>
  );
}

interface GapItemProps {
  gap: GapRow;
  index: number;
  open: boolean;
  onToggle: (index: number) => void;
}

export function GapItem({ gap, index, open, onToggle }: GapItemProps) {
  const local = gap.favorites_kind === "local";
  const id = `gap-${index}`;
  const rankHere = gap.demand_rank >= 51 ? "50+" : String(gap.demand_rank);
  const around =
    gap.ref_rank == null ? "" : gap.ref_rank >= 51 ? " · 50+ around" : ` · #${gap.ref_rank.toFixed(0)} around`;
  const expected = gap.expected_nearby != null ? ` · ~${gap.expected_nearby.toFixed(1)} typical` : "";
  const median = local && gap.median_favorite_km != null ? ` · median ${gap.median_favorite_km} km` : "";
  const favoritesTitle = local
    ? `Places people here love more than the city does${median}`
    : "What people here love (the city's famous spots)";
  const competitors = (gap.competitors ?? []).slice(0, 6);
  const favorites = (gap.favorites ?? []).slice(0, 6);
  const why = gap.why ?? [];
  const blocked = gap.ruled_out ? `Ruled out: ${gap.ruled_out}` : gap.fit && !gap.fit.fits ? `Doesn't fit: ${gap.fit.reason ?? "the unit"}` : null;
  const priced = priceLabel(gap.price?.level);

  return (
    <li
      className={cx("gap", index === 0 && "first", gap.evidence !== "ok" && "thin", open && "open", blocked && "out")}
      style={cssVars({ "--i": index })}
    >
      <button
        className="gap-row"
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-detail`}
        aria-label={`${gap.genre}, gap score ${gap.gap_score}${gap.reading ? `, ${gap.reading}` : ""}`}
        aria-describedby={`${id}-why`}
        onClick={() => {
          onToggle(index);
        }}
      >
        <CountUp className="gap-score" value={gap.gap_score} />
        <span>
          <span className="gap-name">{gap.genre}</span>
          <span className="gap-meta">
            {gap.reading ? <small className={cx("mono reading", reading(gap.reading))}>{gap.reading}</small> : null}
            <small className="mono">
              #{rankHere} here{around}
            </small>
            {gap.source === "agent" ? <small className="mono flag live">tested live by agent</small> : null}
            {gap.source === "owner" ? <small className="mono flag live">your request</small> : null}
          </span>
          {blocked ? <span className="gap-out mono">{blocked}</span> : null}
          <span className="gap-why serif" id={`${id}-why`}>
            {leadLine(gap)}
          </span>
          <span className="gap-bars">
            <span className="meter">
              <span className="mono">
                Inside walk · {gap.nearby_count}
                {gap.nearby_capped ? "+" : ""}
                {expected}
              </span>
              <span className="pips">
                <Pips gap={gap} />
              </span>
            </span>
            <span className="meter">
              <span className="mono">
                {local ? `Favorites outside · ${gap.favorites_far}/${gap.favorites_total}` : "Favorites of people here"}
              </span>
              <span className="dots">
                <Dots gap={gap} />
              </span>
            </span>
          </span>
        </span>
        <span className="gap-toggle" aria-hidden="true">
          +
        </span>
      </button>
      <div className="gap-detail-wrap" id={`${id}-detail`} inert={!open}>
        <div className="gap-detail">
          <div className="gap-detail-inner">
            {why.length || priced ? (
              <div className="gap-evidence">
                <h4 className="label mono">The evidence</h4>
                <ul className="why-list">
                  {why.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                  {gap.price ? (
                    <li className="price-line">
                      {priced ? <b className="mono">Price {priced}. </b> : null}
                      {gap.price.basis}
                      <PriceLadder ladder={gap.price.ladder} level={gap.price.level} />
                      {gap.price.open_note ? <span className="open-note">{gap.price.open_note}</span> : null}
                      <PriceAnchors anchors={gap.price.anchors} />
                    </li>
                  ) : null}
                </ul>
              </div>
            ) : null}
            <div>
              <h4 className="label mono">Competitors inside the walk</h4>
              <ul className="mini">
                {competitors.length ? (
                  competitors.map((place, k) => <Competitor key={`${place.name ?? ""}-${k}`} place={place} />)
                ) : (
                  <li className="muted">Qloo lists no direct competitor inside the walk.</li>
                )}
              </ul>
            </div>
            <div>
              <h4 className="label mono">{favoritesTitle}</h4>
              <ul className="mini">
                {favorites.length ? (
                  favorites.map((place, k) => <Favorite key={`${place.name ?? ""}-${k}`} place={place} />)
                ) : (
                  <li className="muted">No favorites found.</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

/** The server's badge for a gap whose fans travel for it, as older and newer surveys word it. */
const TRAVEL_READINGS = new Set(["Locals travel for it", "People here travel for it"]);

/** The badge's tone: a real gap is highlighted, a crowded or uncertain one is muted. */
function reading(label: string): string {
  if (label === "Clear gap" || label === "Under-supplied" || TRAVEL_READINGS.has(label)) return "strong";
  if (label === "Crowded" || label === "Thin data" || label === "Atypical") return "weak";
  return "";
}

/** The one evidence line that explains the badge; the rest are in the expanded row. */
function leadLine(gap: GapRow): string {
  const why = gap.why ?? [];
  const find = (pattern: RegExp) => why.find((line) => pattern.test(line));
  if (gap.reading && TRAVEL_READINGS.has(gap.reading)) {
    return find(/outside the walk|already inside the walk/) ?? why[0] ?? gapWhy(gap);
  }
  switch (gap.reading) {
    case "Clear gap":
    case "Under-supplied":
    case "Crowded":
      return find(/inside the \d+-minute walk/) ?? why[0] ?? gapWhy(gap);
    case "Thin data":
    case "Atypical":
      return why.at(-1) ?? gapWhy(gap);
    default:
      return why[0] ?? gapWhy(gap);
  }
}
