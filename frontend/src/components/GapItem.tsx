import type { FavoritePlace, GapRow, PlaceCard } from "../api/types";
import { cssVars, cx } from "../lib/css";
import { gapWhy } from "../lib/format";
import { CountUp } from "./CountUp";

const MAX_PIPS = 24;

function Competitor({ place }: { place: PlaceCard }) {
  const complaints = place.complaints ?? [];
  const rating = place.rating ? `★ ${place.rating.toFixed(1)}` : "";
  const praise = (place.praise ?? []).slice(0, 2).join(", ");
  const said = complaints.length ? <span className="bad">{complaints.join(", ")}</span> : praise;
  return (
    <li>
      <span className="n">{place.name}</span>
      {rating || said ? (
        <span className="s">
          {rating}
          {rating && said ? " · " : null}
          {said}
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
  return (
    <li>
      <span className="n">{place.name}</span>
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
  if (gap.favorites_kind !== "local") return <span className="mono muted">same as the city&apos;s famous spots</span>;
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
  const favoritesTitle = local ? `Places locals love more than the city does${median}` : "Locals' favorites (the city's famous spots)";
  const competitors = (gap.competitors ?? []).slice(0, 6);
  const favorites = (gap.favorites ?? []).slice(0, 6);

  return (
    <li className={cx("gap", index === 0 && "first", gap.evidence !== "ok" && "thin", open && "open")} style={cssVars({ "--i": index })}>
      <button
        className="gap-row"
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-detail`}
        aria-label={`${gap.genre}, gap score ${gap.gap_score}`}
        aria-describedby={`${id}-why`}
        onClick={() => {
          onToggle(index);
        }}
      >
        <CountUp className="gap-score" value={gap.gap_score} />
        <span>
          <span className="gap-name">
            {gap.genre}
            <small className="mono muted">
              #{rankHere} here{around}
            </small>
            {gap.evidence === "ok" ? null : (
              <small className="mono flag">{gap.evidence === "thin" ? "thin data" : "atypical"}</small>
            )}
            {gap.source === "agent" ? <small className="mono flag live">tested live by agent</small> : null}
          </span>
          <span className="gap-why serif" id={`${id}-why`}>
            {gapWhy(gap)}
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
                {local ? `Local favorites outside · ${gap.favorites_far}/${gap.favorites_total}` : "Local favorites"}
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
