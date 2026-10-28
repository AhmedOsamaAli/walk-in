import type { ExperienceCard, ExperiencePlan } from "../api/types";
import { Thumbnail } from "./Thumbnail";

const GROUPS = [
  { key: "soundtrack", title: "Soundtrack", what: "Artists to play" },
  { key: "screen", title: "On screen", what: "Films and shows for screen nights" },
  { key: "talks", title: "Talks", what: "Podcasts to host or play" },
] as const;

function Card({ card }: { card: ExperienceCard }) {
  const when = card.year ? String(card.year) : card.since ? `since ${card.since}` : null;
  return (
    <li className="xp-card">
      <Thumbnail image={card.image} name={card.name} />
      <span className="xp-name">{card.name}</span>
      <span className="xp-meta mono">
        {when}
        {card.era ? <i data-era={card.era}>{card.era === "new" ? "New" : "Classic"}</i> : null}
      </span>
    </li>
  );
}

/** What to play, screen and host: what people within 1.5 km over-index on, with each item's era. */
export function ExperiencePlanView({ plan }: { plan: ExperiencePlan }) {
  const groups = GROUPS.filter((group) => plan[group.key]?.length);
  if (!groups.length) return null;
  return (
    <div className="xp">
      {groups.map((group) => (
        <div className="xp-group" key={group.key}>
          <h4 className="xp-title">
            {group.title}
            <span className="mono">{group.what}</span>
          </h4>
          <ul className="xp-cards">
            {(plan[group.key] ?? []).map((card, index) => (
              <Card key={card.id ?? `${card.name ?? ""}-${index}`} card={card} />
            ))}
          </ul>
        </div>
      ))}
      {plan.basis ? <p className="xp-basis mono">{plan.basis}</p> : null}
      {plan.licensing ? <p className="xp-license serif">{plan.licensing}</p> : null}
    </div>
  );
}
