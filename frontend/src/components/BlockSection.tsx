import type { ReactNode } from "react";
import type { BlockPayload, Classic, TopicGroup } from "../api/types";
import { standingText, topicForms } from "../lib/format";
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
              <span className="mono">{classic.genre}</span>
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

/** The block's numbers and voices. `no` is its tab's place in the bar; `area` names the survey's area as the server does
 * ("30-minute drive"). */
export function BlockSection({ no, block, area }: { no: string; block: BlockPayload; area?: string }) {
  const { summary, places } = block;
  const genres = summary.top_genres ?? [];
  const classics = summary.classics ?? [];
  return (
    <section id="s-block" className="sec reveal">
      <SectionHead no={no} title="The block today" note={`Everything Qloo knows inside the ${area ?? "catchment"}.`} />
      <div className="stats stats-3">
        <Stat label="Places">
          <CountUp value={summary.place_count ?? places.length} />
        </Stat>
        <Stat label="Average rating">{summary.avg_rating ? <CountUp value={summary.avg_rating} decimals={2} /> : "—"}</Stat>
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
