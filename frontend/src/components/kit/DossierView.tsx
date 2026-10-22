import type { ReactNode } from "react";
import type {
  Dossier,
  DossierAlternatives,
  DossierBeforeYouSign,
  DossierCase,
  DossierCompetition,
  DossierExperience,
  DossierFirst90,
  DossierKey,
  DossierLaunch,
  DossierMethod,
  DossierOffer,
  DossierRoom,
  DossierTravel,
} from "../../api/kit";
import { cx } from "../../lib/css";
import { distanceText, list, naturalList } from "../../lib/format";
import { CLAIM_KINDS } from "../../lib/launch";
import { HoursText } from "../Hours";
import { PlaceLink, PriceAnchors, PriceLadder } from "../Price";

/** The sections after the cover, as the dossier titles them. */
export const DOSSIER_TITLES: Record<DossierKey, string> = {
  cover: "Cover",
  case: "The case",
  alternatives: "The alternatives",
  competition: "The competition",
  travel: "Where customers go now",
  offer: "Offer and prices",
  room: "The room",
  experience: "The experience",
  launch: "The launch",
  first_90_days: "The first 90 days",
  before_you_sign: "Before you sign",
  method: "Method and limits",
};

/** The sections present after the cover, numbered "01", "02"… in the dossier's order. */
export function dossierContents(dossier: Dossier): { key: DossierKey; no: string; title: string }[] {
  return dossier.sections
    .filter((key) => key !== "cover" && dossier[key])
    .map((key, index) => ({ key, no: String(index + 1).padStart(2, "0"), title: DOSSIER_TITLES[key] }));
}

/** One line on what a section holds, for the contents. */
export function dossierGist(dossier: Dossier, key: DossierKey): string {
  switch (key) {
    case "cover":
      return dossier.cover?.site_label ?? "";
    case "case": {
      const decision = dossier.case?.decision;
      return decision ? `${decision.stamp}: ${decision.reason}` : "";
    }
    case "alternatives":
      return `${dossier.alternatives?.items.length ?? 0} categories set side by side`;
    case "competition": {
      const competition = dossier.competition;
      return competition ? `${competition.count}${competition.capped ? "+" : ""} places of this kind inside the walk` : "";
    }
    case "travel": {
      const travel = dossier.travel;
      return travel ? `${travel.outside} of ${travel.of} loved places are outside the walk` : "";
    }
    case "offer": {
      const offer = dossier.offer;
      return offer ? `${offer.items.length} items people here love${offer.price.label ? `, priced at ${offer.price.label}` : ""}` : "";
    }
    case "room":
      return dossier.room?.capacity ?? (dossier.room?.hours ? `Open ${dossier.room.hours}` : "The interior, the unit and the hours");
    case "experience":
      return "What to play, screen and host";
    case "launch": {
      const launch = dossier.launch;
      return launch ? `${launch.claims.length} claims the ads can make, ${launch.channels.length} channels` : "";
    }
    case "first_90_days":
      return `${dossier.first_90_days?.steps.length ?? 0} steps, from before signing to day 60`;
    case "before_you_sign":
      return `${dossier.before_you_sign?.questions.length ?? 0} questions for the landlord`;
    case "method":
      return "How each number is measured, and where it stops";
  }
}

type Level = 2 | 3;

function Sub({ level, children }: { level: Level; children: ReactNode }) {
  return level === 2 ? <h3 className="dz-sub">{children}</h3> : <h4 className="dz-sub">{children}</h4>;
}

function Basis({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <p className="dz-basis">
      <span className="mono">Basis</span> {text}
    </p>
  );
}

function Case({ data, level }: { data: DossierCase; level: Level }) {
  const { decision } = data;
  const ranked = decision.rank && decision.of ? `#${decision.rank} of ${decision.of}` : null;
  const score = decision.gap_score != null ? `gap score ${decision.gap_score} of 100` : null;
  return (
    <>
      <div className="dz-decision" data-kind={decision.kind} data-level={decision.level}>
        <span className="dz-stamp mono">{decision.stamp}</span>
        <p className="dz-lead">{decision.reason}</p>
        {ranked || score ? <p className="dz-rank mono">{[ranked, score].filter(Boolean).join(" · ")}</p> : null}
        {decision.asked ? (
          <p className="dz-asked">
            You asked about {decision.asked.business}: <b>{decision.asked.stamp}</b>
            {decision.asked.reason ? `. ${decision.asked.reason}` : "."}
          </p>
        ) : null}
        <Basis text={decision.basis} />
      </div>
      {data.caution ? <p className="dz-caution">{data.caution}</p> : null}
      <Sub level={level}>The numbers</Sub>
      <dl className="dz-numbers">
        {data.numbers.map((number) => (
          <div key={number.label}>
            <dt className="mono">{number.label}</dt>
            <dd>
              <b>{number.value}</b>
              <small>{number.basis}</small>
            </dd>
          </div>
        ))}
      </dl>
      <div className="dz-two">
        <div>
          <Sub level={level}>Who it is for</Sub>
          <p className="dz-p">{data.who.text}</p>
          <Basis text={data.who.basis} />
        </div>
        <div>
          <Sub level={level}>The biggest risk</Sub>
          <p className="dz-p">{data.risk.text}</p>
          <p className="dz-p">
            <b>Check before signing:</b> {data.risk.check}
          </p>
          <Basis text={data.risk.basis} />
        </div>
      </div>
      <Basis text={data.basis} />
    </>
  );
}

function Alternatives({ data }: { data: DossierAlternatives }) {
  return (
    <>
      <div className="dz-table-wrap">
        <table className="dz-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Category</th>
              <th scope="col">Gap</th>
              <th scope="col">Reading</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.genre} className={cx(item.chosen && "chosen")}>
                <td className="mono">{item.position ?? "—"}</td>
                <th scope="row">
                  {item.genre}
                  {item.chosen ? <span className="dz-tag mono">This dossier</span> : null}
                  {item.tested_live ? <span className="dz-tag mono">Tested live</span> : null}
                </th>
                <td className="dz-num">{item.gap_score}</td>
                <td>{item.reading}</td>
                <td>
                  {item.why}
                  {item.why_not ? <em className="dz-why-not">{item.why_not}</em> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Basis text={data.basis} />
    </>
  );
}

function Competition({ data, level }: { data: DossierCompetition; level: Level }) {
  return (
    <>
      <p className="dz-p">
        {data.count}
        {data.capped ? "+" : ""} {data.count === 1 ? "place" : "places"} of this kind inside the walk
        {data.places.some((place) => !place.main) ? "; the ones that compete in earnest come first" : ""}.
      </p>
      <div className="dz-table-wrap">
        <table className="dz-table">
          <thead>
            <tr>
              <th scope="col">Place</th>
              <th scope="col">Rating</th>
              <th scope="col">Price</th>
              <th scope="col">Distance</th>
              <th scope="col">Known for</th>
              <th scope="col">What reviews hold against it</th>
            </tr>
          </thead>
          <tbody>
            {data.places.map((place) => (
              <tr key={place.name}>
                <th scope="row">
                  <PlaceLink name={place.name} url={place.url} kind={place.link} />
                </th>
                <td className="dz-num">{place.rating ?? "—"}</td>
                <td className="mono">{place.price ?? "—"}</td>
                <td className="mono">{distanceText(place.distance_m) || "—"}</td>
                <td>{place.known_for.length ? place.known_for.join(", ") : "—"}</td>
                <td>
                  {place.complaints.length
                    ? place.complaints.map((complaint) => (
                        <span className="dz-complaint" key={complaint.theme}>
                          {complaint.theme}
                          {complaint.mentions != null ? <small className="mono"> {complaint.mentions}</small> : null}
                        </span>
                      ))
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.your_answer?.promises.length ? (
        <>
          <Sub level={level}>How to answer them</Sub>
          <ol className="dz-promises">
            {data.your_answer.promises.map((promise) => (
              <li key={promise.theme}>
                <span className="mono">
                  {promise.theme} · {promise.places} {promise.places === 1 ? "place" : "places"}
                  {promise.mentions != null ? `, ${promise.mentions} mentions` : ""}
                </span>
                <b>“{promise.promise}”</b>
                {promise.move ? <span>To keep it: {promise.move}.</span> : null}
              </li>
            ))}
          </ol>
          <Basis text={data.your_answer.basis} />
        </>
      ) : null}
      <Basis text={data.basis} />
    </>
  );
}

function Travel({ data }: { data: DossierTravel }) {
  return (
    <>
      <p className="dz-p">
        {data.outside} of the {data.of} places of this kind that people here love are outside the walk
        {data.median_km != null ? `; the median one is ${data.median_km} km from the site` : ""}.
      </p>
      <ol className="dz-places">
        {data.places.map((place) => (
          <li key={place.name}>
            <span className="dz-place-name">
              <PlaceLink name={place.name} url={place.url} kind={place.link} />
            </span>
            <span className="mono">{[place.km != null ? `${place.km} km` : null, place.price].filter(Boolean).join(" · ")}</span>
            {place.known_for.length ? <span className="dz-known">Known for {naturalList(place.known_for)}</span> : null}
          </li>
        ))}
      </ol>
      <Basis text={data.basis} />
    </>
  );
}

function Offer({ data, level }: { data: DossierOffer; level: Level }) {
  const { price } = data;
  return (
    <>
      {data.items.length ? (
        <>
          <Sub level={level}>What the places people here love are known for</Sub>
          <ol className="dz-items">
            {data.items.map((item) => (
              <li key={item.item}>
                <span>{item.item}</span>
                <span className="mono">
                  {item.places} of {item.of}
                </span>
                {item.new_here ? <span className="dz-tag mono">New to the block</span> : null}
              </li>
            ))}
          </ol>
        </>
      ) : null}
      {data.sheet.length ? (
        <>
          <Sub level={level}>The design sheet&apos;s offer</Sub>
          <p className="dz-p">
            {data.sheet.map((item, index) => (
              <span key={item.item}>
                {index ? " · " : null}
                {item.new_here ? <b>{item.item}</b> : item.item}
              </span>
            ))}
            {data.sheet.some((item) => item.new_here) ? <small className="dz-note"> (in bold: new to the block)</small> : null}
          </p>
        </>
      ) : null}
      <Sub level={level}>Price</Sub>
      <p className="dz-price">
        <b className="mono">{price.label ?? "Not listed"}</b> {price.basis}
      </p>
      <PriceLadder ladder={price.ladder} level={price.level} />
      {price.open_note ? <p className="open-note">{price.open_note}</p> : null}
      <PriceAnchors anchors={price.anchors} />
      <Basis text={data.basis} />
    </>
  );
}

const INTERIOR_LABELS: Record<string, string> = {
  mood: "Mood",
  materials: "Decor & materials",
  lighting: "Lighting",
  layout: "Layout",
  seating: "Seating",
};

function Room({ data }: { data: DossierRoom }) {
  const interior = Object.entries(data.interior ?? {})
    .map(([key, value]) => [INTERIOR_LABELS[key] ?? key, list(value).join(", ")] as const)
    .filter(([, value]) => value);
  const unit = data.unit
    ? [data.unit.size, data.unit.kitchen, data.unit.outdoor_space === "yes" ? "outdoor space" : data.unit.outdoor_space === "none" ? "no outdoor space" : null]
        .filter((part) => part && part !== "unknown")
        .join(", ")
    : "";
  const dna = Object.entries(data.dna ?? {}).filter(([, value]) => list(value).length);
  return (
    <>
      <dl className="spec dz-spec">
        {interior.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        {unit ? (
          <div>
            <dt>Unit</dt>
            <dd>{unit}</dd>
          </div>
        ) : null}
        {data.capacity ? (
          <div>
            <dt>Capacity</dt>
            <dd>
              {data.capacity}
              {data.capacity_basis ? <small className="spec-basis">{data.capacity_basis}</small> : null}
            </dd>
          </div>
        ) : null}
        {data.hours ? (
          <div>
            <dt>Hours</dt>
            <dd>
              <HoursText hours={data.hours} />
              {data.hours_basis ? <small className="spec-basis">{data.hours_basis}</small> : null}
            </dd>
          </div>
        ) : null}
        {dna.map(([family, values]) => (
          <div key={family}>
            <dt>{family.replace(/_/g, " ")}</dt>
            <dd className="tags">
              {list(values).map((value) => (
                <span className="tag" key={value}>
                  {value}
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
      <Basis text={data.basis} />
    </>
  );
}

function Experience({ data }: { data: DossierExperience }) {
  const rows: [string, string[] | undefined][] = [
    ["Play", data.soundtrack],
    ["Screen", data.screen],
    ["Host", data.talks],
  ];
  return (
    <>
      <dl className="spec dz-spec">
        {rows
          .filter((row): row is [string, string[]] => Boolean(row[1]?.length))
          .map(([label, names]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className="tags">
                {names.map((name) => (
                  <span className="tag blue" key={name}>
                    {name}
                  </span>
                ))}
              </dd>
            </div>
          ))}
      </dl>
      {data.licensing ? <p className="dz-note">{data.licensing}</p> : null}
      <Basis text={data.basis} />
    </>
  );
}

function Launch({ data, level }: { data: DossierLaunch; level: Level }) {
  const hoods = data.where?.neighborhoods ?? [];
  return (
    <>
      {data.claims.length ? (
        <>
          <Sub level={level}>What the ads can say</Sub>
          <ol className="claims dz-claims">
            {data.claims.map((claim) => (
              <li className="claim" key={claim.id}>
                <span className="claim-kind mono">{CLAIM_KINDS[claim.kind]}</span>
                <p className="claim-line">
                  <span className="hl">{claim.line}</span>
                </p>
                <p className="claim-proof">
                  <span className="mono">Proof</span> {claim.proof}
                </p>
              </li>
            ))}
          </ol>
        </>
      ) : null}
      {data.notes?.length ? (
        <ul className="dz-notes">
          {data.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {data.channels.length ? (
        <>
          <Sub level={level}>Where to run them</Sub>
          {data.where ? (
            <p className="dz-p">
              The {data.where.minutes}-minute walk
              {data.where.reach_m ? ` reaches ${data.where.reach_m} m at its farthest point` : ""}
              {hoods.length ? `${data.where.reach_m ? " and" : ""} takes in parts of ${naturalList(hoods)}` : ""}.
            </p>
          ) : null}
          <ol className="dz-channels">
            {data.channels.map((channel) => (
              <li key={channel.channel}>
                <b>{channel.channel}</b>
                <span className="dz-setting mono">{channel.setting}</span>
                <span className="dz-why">{channel.why}</span>
              </li>
            ))}
          </ol>
        </>
      ) : null}
      {data.cautions.length ? (
        <div className="launch-cautions dz-cautions">
          <p className="xp-title">Before it runs</p>
          <ul>
            {data.cautions.map((caution) => (
              <li key={caution}>{caution}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <Basis text={data.basis} />
    </>
  );
}

function First90({ data }: { data: DossierFirst90 }) {
  const periods: { when: string; steps: DossierFirst90["steps"] }[] = [];
  for (const step of data.steps) {
    const last = periods.at(-1);
    if (last?.when === step.when) last.steps.push(step);
    else periods.push({ when: step.when, steps: [step] });
  }
  return (
    <>
      <ol className="dz-timeline">
        {periods.map((period) => (
          <li key={period.when}>
            <span className="dz-when mono">{period.when}</span>
            <ul>
              {period.steps.map((step) => (
                <li key={step.do}>
                  <p className="dz-do">{step.do}</p>
                  <p className="dz-step-basis">{step.basis}</p>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      <Basis text={data.basis} />
    </>
  );
}

function BeforeYouSign({ data, level }: { data: DossierBeforeYouSign; level: Level }) {
  return (
    <>
      <Sub level={level}>Ask the landlord</Sub>
      <ol className="dz-questions">
        {data.questions.map((question) => (
          <li key={question.ask}>
            <p className="dz-ask">{question.ask}</p>
            <p className="dz-step-basis">{question.basis}</p>
          </li>
        ))}
      </ol>
      {data.checks?.length ? (
        <>
          <Sub level={level}>Check yourself</Sub>
          <ul className="dz-checks">
            {data.checks.map((check) => (
              <li key={check.risk}>
                <p className="dz-p">{check.risk}</p>
                <p className="dz-p">
                  <b>How:</b> {check.check}
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <Basis text={data.basis} />
    </>
  );
}

function Method({ data, level }: { data: DossierMethod; level: Level }) {
  return (
    <>
      <dl className="dz-method">
        {data.items.map((item) => (
          <div key={item.topic}>
            <dt className="mono">{item.topic}</dt>
            <dd>{item.how}</dd>
          </div>
        ))}
      </dl>
      <Sub level={level}>Freshness</Sub>
      <p className="dz-p">{data.freshness}</p>
      <Sub level={level}>What this does not establish</Sub>
      <ul className="dz-limits">
        {data.limits.map((limit) => (
          <li key={limit}>{limit}</li>
        ))}
      </ul>
      <Basis text={data.basis} />
    </>
  );
}

/** One section's body; its title is the caller's, as a heading or a disclosure's summary. */
export function DossierBody({ dossier, part, level }: { dossier: Dossier; part: DossierKey; level: Level }) {
  switch (part) {
    case "case":
      return dossier.case ? <Case data={dossier.case} level={level} /> : null;
    case "alternatives":
      return dossier.alternatives ? <Alternatives data={dossier.alternatives} /> : null;
    case "competition":
      return dossier.competition ? <Competition data={dossier.competition} level={level} /> : null;
    case "travel":
      return dossier.travel ? <Travel data={dossier.travel} /> : null;
    case "offer":
      return dossier.offer ? <Offer data={dossier.offer} level={level} /> : null;
    case "room":
      return dossier.room ? <Room data={dossier.room} /> : null;
    case "experience":
      return dossier.experience ? <Experience data={dossier.experience} /> : null;
    case "launch":
      return dossier.launch ? <Launch data={dossier.launch} level={level} /> : null;
    case "first_90_days":
      return dossier.first_90_days ? <First90 data={dossier.first_90_days} /> : null;
    case "before_you_sign":
      return dossier.before_you_sign ? <BeforeYouSign data={dossier.before_you_sign} level={level} /> : null;
    case "method":
      return dossier.method ? <Method data={dossier.method} level={level} /> : null;
    case "cover":
      return null;
  }
}
