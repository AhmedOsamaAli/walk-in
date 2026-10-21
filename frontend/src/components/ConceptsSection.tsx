import type { BaselineConcept, ConceptsPayload } from "../api/types";
import { agentCredit } from "../lib/format";
import { Poster } from "./Poster";
import { SectionHead } from "./SectionHead";

function conceptsNote({ mode, model, replayed_from: replayedFrom, note }: ConceptsPayload): string {
  if (mode === "agent") {
    return `Designed by ${agentCredit(model, replayedFrom)} from the gaps above. Every claim traces back to Qloo evidence.`;
  }
  if (mode === "rules") return "Built from the evidence by deterministic rules (no AI model was available).";
  return note ?? "";
}

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
        Plausible, and it would say much the same for almost any block. It has no evidence about who lives within a
        ten-minute walk.
      </p>
    </div>
  );
}

interface ConceptsSectionProps {
  data: ConceptsPayload;
  baseline: BaselineConcept[];
  onOpen: (index: number, opener: HTMLElement | null) => void;
}

export function ConceptsSection({ data, baseline, onOpen }: ConceptsSectionProps) {
  const concepts = data.concepts ?? [];
  return (
    <section id="s-concepts" className="sec reveal">
      <SectionHead no="04" title="What it should become" note={conceptsNote(data)} />
      {concepts.length ? (
        <div className="posters">
          {concepts.map((concept, index) => (
            <Poster key={`${concept.genre}-${index}`} concept={concept} index={index} onOpen={onOpen} />
          ))}
        </div>
      ) : (
        <p className="concepts-empty serif">{data.note ?? "No concepts for this site."}</p>
      )}
      {baseline.length ? <Baseline items={baseline} /> : null}
    </section>
  );
}
