import type { BaselineConcept, ConceptsPayload } from "../api/types";
import { changeNotes, conceptsNote, NOTES_SHOWN, placeConcepts, ruleNames } from "../lib/concepts";
import { Poster } from "./Poster";
import { SectionHead } from "./SectionHead";

/** What a language model suggests with no data, struck through next to the evidence-based concepts. */
function Baseline({ items }: { items: BaselineConcept[] }) {
  return (
    <div className="without">
      <h3 className="label mono">A language model with no data suggested</h3>
      <ul>
        {items.map((item, k) => (
          <li key={k}>
            <s>{item.name ?? item.genre}</s>
            {item.genre ? <span className="mono">{item.genre}</span> : null}
          </li>
        ))}
      </ul>
      <p>
        Plausible, and it would say much the same for almost any block. It has no evidence about the people who live
        here.
      </p>
    </div>
  );
}

interface KeptProps {
  rules: string[];
  notes: string[];
  /** Whether any concept made it: only then do the cards say how they keep the rules. */
  designed: boolean;
}

/** The owner's rules, and what was dropped or changed to keep them and the evidence; a long list folds away. */
function Kept({ rules, notes, designed }: KeptProps) {
  if (!rules.length && !notes.length) return null;
  const changes = (
    <ul className="kept-notes">
      {notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  );
  return (
    <div className="kept">
      {rules.length ? (
        <div className="kept-part">
          <h3 className="kept-label mono">Your rules</h3>
          <ul className="kept-rules">
            {rules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          {designed ? <p className="kept-how">Every concept below keeps them, and each card says how.</p> : null}
        </div>
      ) : null}
      {notes.length > NOTES_SHOWN ? (
        <details className="kept-part kept-changes">
          <summary className="kept-label mono">
            Dropped or changed, and why <span className="kept-count">{notes.length}</span>
          </summary>
          {changes}
        </details>
      ) : notes.length ? (
        <div className="kept-part kept-changes">
          <h3 className="kept-label mono">Dropped or changed, and why</h3>
          {changes}
        </div>
      ) : null}
    </div>
  );
}

interface ConceptsSectionProps {
  no: string;
  data: ConceptsPayload;
  /** The rules the server read from the owner's notes. */
  rules: readonly string[];
  baseline: BaselineConcept[];
  onOpen: (index: number, opener: HTMLElement | null) => void;
}

export function ConceptsSection({ no, data, rules, baseline, onOpen }: ConceptsSectionProps) {
  const placed = placeConcepts(data.concepts ?? []);
  return (
    <section id="s-concepts" className="sec reveal">
      <SectionHead no={no} title="What it should become" note={conceptsNote(data)} />
      {data.caution && placed.length ? <p className="concepts-caution">{data.caution}</p> : null}
      <Kept rules={ruleNames(rules)} notes={changeNotes(data)} designed={placed.length > 0} />
      {placed.length ? (
        <div className="posters">
          {placed.map(({ concept, index, rank }, position) => (
            <Poster
              key={`${concept.genre}-${index}`}
              concept={concept}
              index={index}
              rank={rank}
              position={position}
              onOpen={onOpen}
            />
          ))}
        </div>
      ) : (
        <p className="concepts-empty serif">{data.note ?? "No concepts for this site."}</p>
      )}
      {baseline.length ? <Baseline items={baseline} /> : null}
    </section>
  );
}
