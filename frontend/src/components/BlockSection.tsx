import type { ReactNode } from "react";
import type { BlockPayload, Classic, TopicGroup } from "../api/types";
import { price, standingText, topicForms } from "../lib/format";
import { CountUp } from "./CountUp";
import { SectionHead } from "./SectionHead";

function Stat({ label, note, children }: { label: string; note?: string; children: ReactNode }) {
  return (
    <div className="stat">
      <b>{children}</b>
      <span className="mono">{label}</span>
      {note ? <small className="stat-note mono">{note}</small> : null}
    </div>
  );
}

/** How many places sit at each price level: "$ 35 · $$ 11 · $$$ 6". */
function priceMix(levels: Record<string, number> | undefined): string {
  return Object.entries(levels ?? {})
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([level, count]) => `${"$".repeat(Number(level))} ${count}`)
    .join(" · ");
}

interface TopicsProps {
  title: string;
  groups: TopicGroup[] | undefined;
  kind: "menu" | "experience" | "complaints";
  empty: string;
  limit: number;
}

/** Review keywords grouped by meaning: one row per topic, with the other ways reviews word it underneath. */
function Topics({ title, groups, kind, empty, limit }: TopicsProps) {
  const shown = (groups ?? []).slice(0, limit);
  return (
    <div className="topics-col">
      <h3 className="label mono">{title}</h3>
      <ul className={`topics ${kind}`}>
        {shown.length ? (
          shown.map((group) => {
            const forms = topicForms(group);
            const places = `${group.places} ${group.places === 1 ? "place" : "places"}`;
            return (
              <li key={group.label} title={`${group.mentions.toLocaleString("en-US")} mentions across ${places}`}>
                <span className="t-label">{group.label}</span>
                <small className="t-count">{group.mentions.toLocaleString("en-US")}</small>
                {forms.length ? <span className="t-forms">{forms.join(" · ")}</span> : null}
              </li>
            );
          })
        ) : (
          <li className="muted">{empty}</li>
        )}
      </ul>
    </div>
  );
}

function Classics({ classics }: { classics: Classic[] }) {
  return (
    <>
      <h3 className="label mono">Classics of the block</h3>
      <ul className="classics">
        {classics.map((classic) => (
          <li key={classic.id ?? classic.name}>
            <span className="c-name">{classic.name}</span>
            <span className={classic.michelin ? "badge mono michelin" : "badge mono"}>{standingText(classic)}</span>
            <span className="c-meta">
              <span className="mono">
                {classic.genre}
                {classic.price_level ? ` · ${"$".repeat(classic.price_level)}` : ""}
              </span>
              {classic.known_for.length ? <span> · known for {classic.known_for.join(", ")}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="caption serif">
        Established means a Michelin Guide listing or 250+ TripAdvisor reviews. Qloo has no opening dates, so nothing
        here is called new.
      </p>
    </>
  );
}

function commonestPrice(levels: Record<string, number> | undefined): number | null {
  const [top] = Object.entries(levels ?? {}).sort((a, b) => b[1] - a[1]);
  return top ? Number(top[0]) : null;
}

export function BlockSection({ block }: { block: BlockPayload }) {
  const { summary, places } = block;
  const genres = summary.top_genres ?? [];
  const classics = summary.classics ?? [];
  const typical = commonestPrice(summary.price_levels);
  return (
    <section id="s-block" className="sec reveal">
      <SectionHead no="02" title="The block today" note="Everything Qloo knows inside the walking catchment." />
      <div className="stats">
        <Stat label="Places inside the walk">
          <CountUp value={summary.place_count ?? places.length} />
        </Stat>
        <Stat label="Average rating">{summary.avg_rating ? <CountUp value={summary.avg_rating} decimals={2} /> : "—"}</Stat>
        <Stat label="Most common price" note={priceMix(summary.price_levels)}>
          {typical ? price(typical) : "—"}
        </Stat>
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
      {classics.length ? <Classics classics={classics} /> : null}
      <div className="voices">
        <Topics title="On the menu" groups={summary.menu} kind="menu" empty="No dishes in the reviews nearby." limit={8} />
        <Topics
          title="What people come for"
          groups={summary.experience}
          kind="experience"
          empty="No recurring experiences in the reviews."
          limit={8}
        />
      </div>
      <Topics
        title="What reviews complain about"
        groups={summary.complaints}
        kind="complaints"
        empty="No recurring complaints."
        limit={6}
      />
    </section>
  );
}
