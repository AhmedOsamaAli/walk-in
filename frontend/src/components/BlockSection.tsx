import type { ReactNode } from "react";
import type { BlockPayload, Tally } from "../api/types";
import { price } from "../lib/format";
import { CountUp } from "./CountUp";
import { SectionHead } from "./SectionHead";

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="stat">
      <b>{children}</b>
      <span className="mono">{label}</span>
    </div>
  );
}

function TallyList({ rows, className, empty }: { rows: Tally[] | undefined; className: string; empty: string }) {
  const shown = (rows ?? []).slice(0, 7);
  return (
    <ul className={className}>
      {shown.length ? (
        shown.map(([key, count]) => (
          <li key={key}>
            <span>{key}</span>
            <small>{count}</small>
          </li>
        ))
      ) : (
        <li className="muted">{empty}</li>
      )}
    </ul>
  );
}

function commonestPrice(levels: Record<string, number> | undefined): number | null {
  const [top] = Object.entries(levels ?? {}).sort((a, b) => b[1] - a[1]);
  return top ? Number(top[0]) : null;
}

export function BlockSection({ block }: { block: BlockPayload }) {
  const { summary, places } = block;
  const genres = summary.top_genres ?? [];
  const typical = commonestPrice(summary.price_levels);
  return (
    <section id="s-block" className="sec reveal">
      <SectionHead no="02" title="The block today" note="Everything Qloo knows inside the walking catchment." />
      <div className="stats">
        <Stat label="Places inside the walk">
          <CountUp value={summary.place_count ?? places.length} />
        </Stat>
        <Stat label="Average rating">{summary.avg_rating ? <CountUp value={summary.avg_rating} decimals={2} /> : "—"}</Stat>
        <Stat label="Most common price">{typical ? price(typical) : "—"}</Stat>
        <Stat label="Place types">
          <CountUp value={genres.length} />
        </Stat>
      </div>
      <h3 className="label mono">Most common here</h3>
      <div className="tags">
        {genres.length ? (
          genres.map(([name, count]) => (
            <span className="tag" key={name}>
              {name} <small>{count}</small>
            </span>
          ))
        ) : (
          <span className="muted">No genre data.</span>
        )}
      </div>
      <div className="voices">
        <div className="voice">
          <h3 className="label mono">What reviews praise</h3>
          <TallyList rows={summary.praise} className="praise" empty="No review keywords nearby." />
        </div>
        <div className="voice">
          <h3 className="label mono">What reviews complain about</h3>
          <TallyList rows={summary.complaints} className="complaints" empty="No recurring complaints." />
        </div>
      </div>
    </section>
  );
}
