import { useEffect, useState } from "react";
import { messageOf } from "../api/client";
import type { Concept, Design, ExperiencePlan } from "../api/types";
import { audienceTitle } from "../lib/audience";
import { letter, list, naturalList } from "../lib/format";
import { areaText, hasLaunchPlan } from "../lib/launch";
import { offerItems, unitText, type OfferItem, type OfferMark } from "../lib/sheet";
import { loadDesign } from "../state/designs";
import { WhoYoudWin } from "./AudienceView";
import { ErrorBoundary } from "./ErrorBoundary";
import { ExperiencePlanView } from "./ExperiencePlan";
import { HoursText } from "./Hours";
import { KitOffer } from "./KitOffer";
import { LaunchPlanView } from "./LaunchPlan";

interface SheetProps {
  runId: string;
  index: number;
  concept: Concept;
}

const MARKS: Record<Exclude<OfferMark, null>, string> = {
  loved: "Known at loved places",
  new: "New to the block",
};

const hasExperience = (plan: ExperiencePlan | null | undefined): plan is ExperiencePlan =>
  [plan?.soundtrack, plan?.screen, plan?.talks].some((group) => Boolean(group?.length));

function Drafting({ concept, index }: Omit<SheetProps, "runId">) {
  return (
    <div className="d-main">
      <p className="d-eyebrow mono">Design sheet · Concept {letter(index)} · drafting</p>
      <h2 className="d-title" id="design-title">
        {concept.name}
      </h2>
      <div className="sk sk-line" />
      <div className="sk sk-line" />
      <div className="sk sk-block" />
      <div className="sk sk-block short" />
    </div>
  );
}

function SheetError({ concept, message }: { concept: Concept; message: string }) {
  return (
    <div className="d-main">
      <p className="d-eyebrow mono">Design sheet</p>
      <h2 className="d-title" id="design-title">
        {concept.name}
      </h2>
      <p className="d-p">{message}</p>
    </div>
  );
}

/** What to play, screen and host. The licensing note follows the soundtrack it is mostly about; screenings and talks,
 * where the concept has them, come after it. */
function Experience({ plan }: { plan: ExperiencePlan }) {
  const { soundtrack, screen, talks, basis, licensing } = plan;
  if (!soundtrack?.length || !(screen?.length || talks?.length)) return <ExperiencePlanView plan={plan} />;
  return (
    <div className="d-xp">
      <ExperiencePlanView plan={{ soundtrack, licensing }} />
      <ExperiencePlanView plan={{ screen, talks, basis }} />
    </div>
  );
}

/** What it sells, each item marked where the concept's evidence says the places people here love are known for it. */
function Offer({ items, concept, area }: { items: OfferItem[]; concept: Concept; area: string }) {
  const marks = new Set(items.map((item) => item.mark));
  const loved = list(concept.inspired_by).slice(0, 3);
  return (
    <>
      <h3 className="d-h">The offer</h3>
      <ol className="offer">
        {items.map(({ item, mark }) => (
          <li key={item}>
            <span className="offer-line">
              <span className="offer-item">{item}</span>
              {mark ? (
                <span className="offer-mark mono" data-mark={mark}>
                  {MARKS[mark]}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
      {marks.has("loved") || marks.has("new") ? (
        <dl className="offer-key">
          {marks.has("loved") ? (
            <div>
              <dt>
                <span className="offer-mark mono" data-mark="loved">
                  {MARKS.loved}
                </span>
              </dt>
              <dd>
                {`What Qloo shows the places of this kind people here love${loved.length ? `, such as ${naturalList(loved)},` : ""} are known for.`}
              </dd>
            </div>
          ) : null}
          {marks.has("new") ? (
            <div>
              <dt>
                <span className="offer-mark mono" data-mark="new">
                  {MARKS.new}
                </span>
              </dt>
              <dd>Known at those places, and at no place inside the {area}.</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </>
  );
}

/** When it opens and what the unit holds, each with what it rests on. */
function Room({ design }: { design: Design }) {
  const unit = unitText(design.unit);
  const { hours, capacity } = design;
  if (!hours && !unit && !capacity) return null;
  const title = hours && (unit || capacity) ? "Hours and the unit" : hours ? "Hours" : "The unit";
  return (
    <>
      <h3 className="d-h">{title}</h3>
      <dl className="spec">
        {hours ? (
          <div>
            <dt>Hours</dt>
            <dd>
              <HoursText hours={hours} />
              {design.hours_basis ? <small className="spec-basis">{design.hours_basis}</small> : null}
            </dd>
          </div>
        ) : null}
        {unit ? (
          <div>
            <dt>Unit</dt>
            <dd>{unit}</dd>
          </div>
        ) : null}
        {capacity ? (
          <div>
            <dt>Capacity</dt>
            <dd>
              {capacity}
              {design.capacity_basis ? <small className="spec-basis">{design.capacity_basis}</small> : null}
            </dd>
          </div>
        ) : null}
      </dl>
    </>
  );
}

function Sheet({ runId, index, concept, design }: SheetProps & { design: Design }) {
  const name = design.name ?? concept.name;
  const tagline = design.tagline ?? concept.one_liner;
  const offer = offerItems(design, concept);
  const area = design.launch ? areaText(design.launch.where) : "area";
  const rules = list(design.owner_rules).map((line) => line.trim());
  const madeBy = design.mode === "agent" ? (design.model ?? "agent") : "evidence rules";

  return (
    <div className="d-main">
      <p className="d-eyebrow mono">
        Design sheet · Concept {letter(index)} · {concept.genre} · {madeBy}
      </p>
      <h2 className="d-title" id="design-title">
        {name}
      </h2>
      {tagline ? <p className="d-tagline">{tagline}</p> : null}
      {offer.length ? <Offer items={offer} concept={concept} area={area} /> : null}
      {design.audience ? (
        <>
          <h3 className="d-h">{audienceTitle(design.audience)}</h3>
          <WhoYoudWin audience={design.audience} area={area} />
        </>
      ) : null}
      <Room design={design} />
      {rules.length ? (
        <>
          <h3 className="d-h">Your rules</h3>
          <ul className="d-rules">
            {rules.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      ) : null}
      {hasExperience(design.experience) ? (
        <>
          <h3 className="d-h">Experience</h3>
          <Experience plan={design.experience} />
        </>
      ) : null}
      {hasLaunchPlan(design.launch) ? (
        <>
          <h3 className="d-h">Launch</h3>
          <p className="d-p launch-lede">
            Who to reach, where and when, and only what the evidence lets an ad say. Paste the settings into each
            platform.
          </p>
          <LaunchPlanView plan={design.launch} peopleAbove={Boolean(design.audience)} />
        </>
      ) : null}
      <h3 className="d-h">Launch kit</h3>
      <KitOffer runId={runId} index={index} name={name} plan={design.launch} />
    </div>
  );
}

/** A concept's design sheet: what it sells, when it opens, what the unit holds, the owner's rules, the experience,
 * the launch and its kit. A part with nothing to say is left out. */
export function DesignContent({ runId, index, concept }: SheetProps) {
  const [loaded, setLoaded] = useState<{ design: Design } | { error: string } | null>(null);

  useEffect(() => {
    let live = true;
    loadDesign(runId, index).then(
      (design) => {
        if (live) setLoaded({ design });
      },
      (error: unknown) => {
        if (live) setLoaded({ error: messageOf(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [runId, index]);

  return (
    <div className="design-body" aria-busy={loaded === null}>
      {loaded === null ? (
        <Drafting concept={concept} index={index} />
      ) : "error" in loaded ? (
        <SheetError concept={concept} message={loaded.error} />
      ) : (
        <ErrorBoundary
          fallback={<SheetError concept={concept} message="This sheet could not be drawn. Run the site again, or open another concept." />}
        >
          <Sheet runId={runId} index={index} concept={concept} design={loaded.design} />
        </ErrorBoundary>
      )}
    </div>
  );
}